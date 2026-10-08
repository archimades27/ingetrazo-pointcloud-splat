#include <stdint.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <dispatch/dispatch.h>

#define MAX_RADIUS 128.0f
#define NUM_SLICES 16

static inline float fast_exp(float x) {
    if (x < -6.0f) return 0.0f;
    return expf(x);
}

typedef struct {
    float px, py;
    float A, B, C;
    int min_x, max_x, min_y, max_y;
    uint8_t r, g, b;
    float base_alpha;
} SplatData;

typedef struct {
    int *indices;
    int count;
    int capacity;
} SliceBin;

void sort_splats_depth_c(
    const float *pts,
    int n,
    const float *obj_mat,
    float eye_x, float eye_y, float eye_z,
    float fwd_x, float fwd_y, float fwd_z,
    int32_t *out_order,
    int max_draw,
    int *out_count
) {
    if (n <= 0 || !pts || !out_order) {
        if (out_count) *out_count = 0;
        return;
    }

    float O00 = obj_mat[0], O01 = obj_mat[1], O02 = obj_mat[2], O03 = obj_mat[3];
    float O10 = obj_mat[4], O11 = obj_mat[5], O12 = obj_mat[6], O13 = obj_mat[7];
    float O20 = obj_mat[8], O21 = obj_mat[9], O22 = obj_mat[10], O23 = obj_mat[11];
    int has_obj = (O00 != 1.0f || O11 != 1.0f || O22 != 1.0f ||
                   O01 != 0.0f || O02 != 0.0f || O10 != 0.0f ||
                   O12 != 0.0f || O20 != 0.0f || O21 != 0.0f ||
                   O03 != 0.0f || O13 != 0.0f || O23 != 0.0f);

    int stride = (max_draw > 0 && n > max_draw) ? (n / max_draw) : 1;
    if (stride < 1) stride = 1;
    int n_sort = n / stride;
    if (max_draw > 0 && n_sort > max_draw) n_sort = max_draw;
    if (n_sort <= 0) {
        if (out_count) *out_count = 0;
        return;
    }

    float *depths = (float *)malloc(sizeof(float) * n_sort);
    if (!depths) {
        if (out_count) *out_count = 0;
        return;
    }

    int chunk_size = 16384;
    int n_chunks = (n_sort + chunk_size - 1) / chunk_size;
    dispatch_queue_t queue = dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_HIGH, 0);

    dispatch_apply(n_chunks, queue, ^(size_t chunk_idx) {
        int start = (int)chunk_idx * chunk_size;
        int end = start + chunk_size;
        if (end > n_sort) end = n_sort;

        if (has_obj) {
            for (int j = start; j < end; j++) {
                int i = j * stride;
                float x = pts[i * 3 + 0];
                float y = pts[i * 3 + 1];
                float z = pts[i * 3 + 2];
                float wx = O00 * x + O01 * y + O02 * z + O03;
                float wy = O10 * x + O11 * y + O12 * z + O13;
                float wz = O20 * x + O21 * y + O22 * z + O23;
                depths[j] = (wx - eye_x) * fwd_x + (wy - eye_y) * fwd_y + (wz - eye_z) * fwd_z;
            }
        } else {
            for (int j = start; j < end; j++) {
                int i = j * stride;
                float wx = pts[i * 3 + 0];
                float wy = pts[i * 3 + 1];
                float wz = pts[i * 3 + 2];
                depths[j] = (wx - eye_x) * fwd_x + (wy - eye_y) * fwd_y + (wz - eye_z) * fwd_z;
            }
        }
    });

    float d_min = depths[0];
    float d_max = depths[0];
    for (int j = 1; j < n_sort; j++) {
        if (depths[j] < d_min) d_min = depths[j];
        if (depths[j] > d_max) d_max = depths[j];
    }
    float span = d_max - d_min;
    if (span < 1e-4f) span = 1e-4f;
    float scale = 65535.0f / span;

    int *hist = (int *)calloc(65536, sizeof(int));
    uint16_t *q_depths = (uint16_t *)malloc(sizeof(uint16_t) * n_sort);
    if (!hist || !q_depths) {
        if (hist) free(hist);
        if (q_depths) free(q_depths);
        free(depths);
        if (out_count) *out_count = 0;
        return;
    }

    for (int j = 0; j < n_sort; j++) {
        float qf = (depths[j] - d_min) * scale;
        int qi = (int)qf;
        if (qi < 0) qi = 0;
        else if (qi > 65535) qi = 65535;
        q_depths[j] = (uint16_t)qi;
        hist[qi]++;
    }

    int *pos = (int *)malloc(sizeof(int) * 65536);
    if (!pos) {
        free(hist);
        free(q_depths);
        free(depths);
        if (out_count) *out_count = 0;
        return;
    }

    int total = 0;
    // Largest depth first (furthest first for correct back-to-front compositing)
    for (int b = 65535; b >= 0; b--) {
        pos[b] = total;
        total += hist[b];
    }

    for (int j = 0; j < n_sort; j++) {
        uint16_t q = q_depths[j];
        out_order[pos[q]++] = (int32_t)(j * stride);
    }

    if (out_count) *out_count = n_sort;

    free(pos);
    free(q_depths);
    free(hist);
    free(depths);
}

void rasterize_splats_direct(
    uint8_t *buf,               // Frame buffer [h, w, 4] in ARGB32 (B, G, R, A)
    int width,
    int height,
    int n_draw,                 // Number of splats to draw
    const int32_t *order,       // Sorted indices into original arrays (furthest first)
    const float *coords,        // Original coords [N, 3]
    const float *scales,        // Original scales [N, 3]
    const float *rotations,     // Original quaternions [N, 4] (w, x, y, z)
    const uint8_t *colors,      // Original colors [N, 4] (R, G, B, A)
    const float *obj_mat,       // Object transform: R_obj (3x3 row-major) and T_obj (3)
    const float *view_mat,      // Camera view rotation W: 3x3 row-major (9 floats: R00..R02, R10..R12, R20..R22)
    const float *cam_eye,       // Camera world position (eye_x, eye_y, eye_z)
    float fx,
    float fy,
    float cx,
    float cy,
    float splat_scale,
    float opacity_mul,
    const float *clip_plane     // Optional section cut plane [nx, ny, nz, d] or NULL
) {
    if (!buf || width <= 0 || height <= 0 || n_draw <= 0) return;

    // View rotation matrix:
    // row 0: R00, R01, R02
    // row 1: R10, R11, R12
    // row 2: R20, R21, R22
    float R00 = view_mat[0], R01 = view_mat[1], R02 = view_mat[2];
    float R10 = view_mat[3], R11 = view_mat[4], R12 = view_mat[5];
    float R20 = view_mat[6], R21 = view_mat[7], R22 = view_mat[8];

    float eye_x = cam_eye[0], eye_y = cam_eye[1], eye_z = cam_eye[2];

    // Object transform: [O00 O01 O02 Tx, O10 O11 O12 Ty, O20 O21 O22 Tz]
    float O00 = obj_mat[0], O01 = obj_mat[1], O02 = obj_mat[2], O03 = obj_mat[3];
    float O10 = obj_mat[4], O11 = obj_mat[5], O12 = obj_mat[6], O13 = obj_mat[7];
    float O20 = obj_mat[8], O21 = obj_mat[9], O22 = obj_mat[10], O23 = obj_mat[11];
    int has_obj_xform = (O00 != 1.0f || O11 != 1.0f || O22 != 1.0f ||
                         O01 != 0.0f || O02 != 0.0f || O10 != 0.0f ||
                         O12 != 0.0f || O20 != 0.0f || O21 != 0.0f ||
                         O03 != 0.0f || O13 != 0.0f || O23 != 0.0f);

    int has_clip = (clip_plane != NULL);
    float c_nx = 0.0f, c_ny = 0.0f, c_nz = 0.0f, c_d = 0.0f;
    if (has_clip) {
        c_nx = clip_plane[0];
        c_ny = clip_plane[1];
        c_nz = clip_plane[2];
        c_d = clip_plane[3];
    }

    SplatData *splats = (SplatData *)malloc(sizeof(SplatData) * n_draw);
    if (!splats) return;

    dispatch_queue_t queue = dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_HIGH, 0);

    // Phase 1: Parallel projection & geometry setup
    int chunk_size = 4096;
    int n_chunks = (n_draw + chunk_size - 1) / chunk_size;

    dispatch_apply(n_chunks, queue, ^(size_t chunk_idx) {
        int start = (int)chunk_idx * chunk_size;
        int end = start + chunk_size;
        if (end > n_draw) end = n_draw;

        for (int k = start; k < end; k++) {
            splats[k].base_alpha = 0.0f;
            int i = order[k];

            // 1. World space position
            float x = coords[i * 3 + 0];
            float y = coords[i * 3 + 1];
            float z_w = coords[i * 3 + 2];
            float wx = x, wy = y, wz = z_w;
            if (has_obj_xform) {
                wx = O00 * x + O01 * y + O02 * z_w + O03;
                wy = O10 * x + O11 * y + O12 * z_w + O13;
                wz = O20 * x + O21 * y + O22 * z_w + O23;
            }

            // Section plane cut culling
            if (has_clip) {
                float dist = c_nx * wx + c_ny * wy + c_nz * wz + c_d;
                if (dist < 0.0f) continue;
            }

            // 2. Camera space position: (R_view * (world_pt - eye))
            float dx_eye = wx - eye_x;
            float dy_eye = wy - eye_y;
            float dz_eye = wz - eye_z;
            float c_x = R00 * dx_eye + R01 * dy_eye + R02 * dz_eye;
            float c_y = R10 * dx_eye + R11 * dy_eye + R12 * dz_eye;
            float c_z = R20 * dx_eye + R21 * dy_eye + R22 * dz_eye;

            // Camera looks down -Z in IngeTrazo view coordinates
            float z = -c_z;
            if (z <= 0.05f) continue;

            // 3. Screen coordinates
            float inv_z = 1.0f / z;
            float p_x = fx * (c_x * inv_z) + cx;
            float p_y = -fy * (c_y * inv_z) + cy; // Inverted Y for window pixels

            if (p_x < -MAX_RADIUS || p_x >= width + MAX_RADIUS ||
                p_y < -MAX_RADIUS || p_y >= height + MAX_RADIUS) {
                continue;
            }

            const uint8_t *col = &colors[i * 4];
            float base_alpha = (col[3] / 255.0f) * opacity_mul;
            if (base_alpha < 0.005f) continue;

            // 4. Quaternion rotation & scale
            float qw = rotations[i * 4 + 0];
            float qx = rotations[i * 4 + 1];
            float qy = rotations[i * 4 + 2];
            float qz = rotations[i * 4 + 3];
            float q_norm = sqrtf(qw * qw + qx * qx + qy * qy + qz * qz);
            if (q_norm > 0.0f) {
                float inv_q = 1.0f / q_norm;
                qw *= inv_q; qx *= inv_q; qy *= inv_q; qz *= inv_q;
            }

            float r00 = 1.0f - 2.0f * (qy * qy + qz * qz);
            float r01 = 2.0f * (qx * qy - qw * qz);
            float r02 = 2.0f * (qx * qz + qw * qy);

            float r10 = 2.0f * (qx * qy + qw * qz);
            float r11 = 1.0f - 2.0f * (qx * qx + qz * qz);
            float r12 = 2.0f * (qy * qz - qw * qx);

            float r20 = 2.0f * (qx * qz - qw * qy);
            float r21 = 2.0f * (qy * qz + qw * qx);
            float r22 = 1.0f - 2.0f * (qx * qx + qy * qy);

            float sx = scales[i * 3 + 0] * splat_scale;
            float sy = scales[i * 3 + 1] * splat_scale;
            float sz = scales[i * 3 + 2] * splat_scale;

            float M00 = r00 * sx, M10 = r10 * sx, M20 = r20 * sx;
            float M01 = r01 * sy, M11 = r11 * sy, M21 = r21 * sy;
            float M02 = r02 * sz, M12 = r12 * sz, M22 = r22 * sz;

            // If object has rotation, combine R_obj with M
            if (has_obj_xform) {
                float nM00 = O00 * M00 + O01 * M10 + O02 * M20;
                float nM10 = O10 * M00 + O11 * M10 + O12 * M20;
                float nM20 = O20 * M00 + O21 * M10 + O22 * M20;

                float nM01 = O00 * M01 + O01 * M11 + O02 * M21;
                float nM11 = O10 * M01 + O11 * M11 + O12 * M21;
                float nM21 = O20 * M01 + O21 * M11 + O22 * M21;

                float nM02 = O00 * M02 + O01 * M12 + O02 * M22;
                float nM12 = O10 * M02 + O11 * M12 + O12 * M22;
                float nM22 = O20 * M02 + O21 * M12 + O22 * M22;

                M00 = nM00; M10 = nM10; M20 = nM20;
                M01 = nM01; M11 = nM11; M21 = nM21;
                M02 = nM02; M12 = nM12; M22 = nM22;
            }

            // Transform into camera space: T = R_view * M
            float T00 = R00 * M00 + R01 * M10 + R02 * M20;
            float T10 = R10 * M00 + R11 * M10 + R12 * M20;
            float T20 = R20 * M00 + R21 * M10 + R22 * M20;

            float T01 = R00 * M01 + R01 * M11 + R02 * M21;
            float T11 = R10 * M01 + R11 * M11 + R12 * M21;
            float T21 = R20 * M01 + R21 * M11 + R22 * M21;

            float T02 = R00 * M02 + R01 * M12 + R02 * M22;
            float T12 = R10 * M02 + R11 * M12 + R12 * M22;
            float T22 = R20 * M02 + R21 * M12 + R22 * M22;

            float inv_z2 = inv_z * inv_z;
            float J00 = fx * inv_z,  J02 = fx * c_x * inv_z2;
            float J11 = -fy * inv_z, J12 = -fy * c_y * inv_z2;

            float V00 = J00 * T00 + J02 * T20;
            float V01 = J00 * T01 + J02 * T21;
            float V02 = J00 * T02 + J02 * T22;

            float V10 = J11 * T10 + J12 * T20;
            float V11 = J11 * T11 + J12 * T21;
            float V12 = J11 * T12 + J12 * T22;

            float a = V00 * V00 + V01 * V01 + V02 * V02 + 0.3f;
            float b = V00 * V10 + V01 * V11 + V02 * V12;
            float c = V10 * V10 + V11 * V11 + V12 * V12 + 0.3f;

            float det = a * c - b * b;
            if (det <= 0.0001f) continue;

            float inv_det = 1.0f / det;
            float A_conic = c * inv_det;
            float B_conic = -b * inv_det;
            float C_conic = a * inv_det;

            float mid = 0.5f * (a + c);
            float term = mid * mid - det;
            float disc = sqrtf(term > 0.0f ? term : 0.0f);
            float lambda1 = mid + disc;
            float radius = ceilf(3.0f * sqrtf(lambda1 > 0.1f ? lambda1 : 0.1f));
            if (radius < 1.0f) radius = 1.0f;
            if (radius > MAX_RADIUS) radius = MAX_RADIUS;

            int min_x = (int)floorf(p_x - radius);
            int max_x = (int)ceilf(p_x + radius);
            int min_y = (int)floorf(p_y - radius);
            int max_y = (int)ceilf(p_y + radius);

            if (min_x < 0) min_x = 0;
            if (max_x >= width) max_x = width - 1;
            if (min_y < 0) min_y = 0;
            if (max_y >= height) max_y = height - 1;
            if (min_x > max_x || min_y > max_y) continue;

            splats[k].px = p_x;
            splats[k].py = p_y;
            splats[k].A = A_conic;
            splats[k].B = B_conic;
            splats[k].C = C_conic;
            splats[k].min_x = min_x;
            splats[k].max_x = max_x;
            splats[k].min_y = min_y;
            splats[k].max_y = max_y;
            splats[k].r = col[0];
            splats[k].g = col[1];
            splats[k].b = col[2];
            splats[k].base_alpha = base_alpha;
        }
    });

    // Phase 2: Bin valid splats into vertical slices
    SliceBin *bins = (SliceBin *)malloc(sizeof(SliceBin) * NUM_SLICES);
    if (!bins) {
        free(splats);
        return;
    }
    int approx_capacity = n_draw / (NUM_SLICES / 2) + 1024;
    for (int s = 0; s < NUM_SLICES; s++) {
        bins[s].count = 0;
        bins[s].capacity = approx_capacity;
        bins[s].indices = (int *)malloc(sizeof(int) * approx_capacity);
        if (!bins[s].indices) {
            for (int j = 0; j < s; j++) free(bins[j].indices);
            free(bins);
            free(splats);
            return;
        }
    }

    int slice_h = (height + NUM_SLICES - 1) / NUM_SLICES;
    for (int k = 0; k < n_draw; k++) {
        if (splats[k].base_alpha <= 0.0f) continue;
        int s_start = splats[k].min_y / slice_h;
        int s_end = splats[k].max_y / slice_h;
        if (s_start < 0) s_start = 0;
        if (s_end >= NUM_SLICES) s_end = NUM_SLICES - 1;

        for (int s = s_start; s <= s_end; s++) {
            if (bins[s].count >= bins[s].capacity) {
                int new_cap = bins[s].capacity * 2;
                int *new_ind = (int *)realloc(bins[s].indices, sizeof(int) * new_cap);
                if (!new_ind) continue;
                bins[s].capacity = new_cap;
                bins[s].indices = new_ind;
            }
            bins[s].indices[bins[s].count++] = k;
        }
    }

    // Phase 3: Parallel slice rasterization
    SliceBin *captured_bins = bins;
    dispatch_apply(NUM_SLICES, queue, ^(size_t slice_idx) {
        int slice_y0 = (int)slice_idx * slice_h;
        int slice_y1 = slice_y0 + slice_h - 1;
        if (slice_y1 >= height) slice_y1 = height - 1;
        if (slice_y0 > slice_y1) return;

        SliceBin *b = &captured_bins[slice_idx];
        int num_items = b->count;
        const int *idx_list = b->indices;

        for (int k = 0; k < num_items; k++) {
            int idx = idx_list[k];
            int y_start = splats[idx].min_y;
            int y_end = splats[idx].max_y;
            if (y_start < slice_y0) y_start = slice_y0;
            if (y_end > slice_y1) y_end = slice_y1;
            if (y_start > y_end) continue;

            int min_x = splats[idx].min_x;
            int max_x = splats[idx].max_x;
            float p_x = splats[idx].px;
            float p_y = splats[idx].py;
            float A_conic = splats[idx].A;
            float B_conic = splats[idx].B;
            float C_conic = splats[idx].C;
            float base_alpha = splats[idx].base_alpha;
            uint8_t r_src = splats[idx].r;
            uint8_t g_src = splats[idx].g;
            uint8_t b_src = splats[idx].b;

            for (int y = y_start; y <= y_end; y++) {
                float dy = (float)y - p_y;
                float C_dy = C_conic * dy * dy;
                float two_B_dy = 2.0f * B_conic * dy;
                uint8_t *row = &buf[(y * width + min_x) * 4];

                for (int x = min_x; x <= max_x; x++, row += 4) {
                    float dx = (float)x - p_x;
                    float power = -0.5f * (A_conic * dx * dx + two_B_dy * dx + C_dy);
                    if (power > 0.0f || power < -4.5f) continue;

                    float alpha = base_alpha * fast_exp(power);
                    if (alpha < 0.004f) continue;

                    int a_int = (int)(alpha * 255.0f + 0.5f);
                    if (a_int <= 0) continue;
                    if (a_int > 255) a_int = 255;
                    int inv_a = 255 - a_int;

                    row[0] = (uint8_t)((b_src * a_int + row[0] * inv_a + 127) / 255);
                    row[1] = (uint8_t)((g_src * a_int + row[1] * inv_a + 127) / 255);
                    row[2] = (uint8_t)((r_src * a_int + row[2] * inv_a + 127) / 255);
                    row[3] = (uint8_t)((255 * a_int + row[3] * inv_a + 127) / 255);
                }
            }
        }
    });

    for (int s = 0; s < NUM_SLICES; s++) {
        free(bins[s].indices);
    }
    free(bins);
    free(splats);
}

int rasterize_splats_auto(
    uint8_t *buf,
    int width,
    int height,
    int n_total,
    int max_draw,
    const float *coords,
    const float *scales,
    const float *rotations,
    const uint8_t *colors,
    const float *obj_mat,
    const float *view_mat,
    const float *cam_eye,
    float fwd_x, float fwd_y, float fwd_z,
    float fx, float fy, float cx, float cy,
    float splat_scale, float opacity_mul,
    int clear_buf,
    const float *clip_plane
) {
    if (!buf || width <= 0 || height <= 0 || n_total <= 0) return 0;

    if (clear_buf) {
        memset(buf, 0, (size_t)width * height * 4);
    }

    int budget = (max_draw > 0 && max_draw < n_total) ? max_draw : n_total;
    int32_t *order = (int32_t *)malloc(sizeof(int32_t) * budget);
    if (!order) return 0;

    int n_draw = 0;
    sort_splats_depth_c(
        coords, n_total, obj_mat,
        cam_eye[0], cam_eye[1], cam_eye[2],
        fwd_x, fwd_y, fwd_z,
        order, budget, &n_draw
    );

    if (n_draw > 0) {
        rasterize_splats_direct(
            buf, width, height, n_draw, order,
            coords, scales, rotations, colors,
            obj_mat, view_mat, cam_eye,
            fx, fy, cx, cy, splat_scale, opacity_mul,
            clip_plane
        );
    }

    free(order);
    return n_draw;
}

void rasterize_point_cloud_auto(
    uint8_t *buf,
    int width,
    int height,
    int n_points,
    const float *coords,
    const uint8_t *colors,
    const float *obj_mat,
    const float *view_mat,
    const float *cam_eye,
    float fx, float fy, float cx, float cy,
    int point_size,
    float opacity_mul,
    int clear_buf,
    int is_ortho,
    const float *clip_plane
) {
    if (!buf || width <= 0 || height <= 0 || n_points <= 0) return;

    if (clear_buf) {
        memset(buf, 0, (size_t)width * height * 4);
    }

    size_t n_pixels = (size_t)width * height;
    uint32_t *depth_buf = (uint32_t *)malloc(n_pixels * sizeof(uint32_t));
    if (!depth_buf) return;
    for (size_t i = 0; i < n_pixels; i++) {
        depth_buf[i] = 0x7FFFFFFF;
    }

    uint32_t *cbuf32 = (uint32_t *)buf;

    float W00 = view_mat[0], W01 = view_mat[1], W02 = view_mat[2];
    float W10 = view_mat[3], W11 = view_mat[4], W12 = view_mat[5];
    float W20 = view_mat[6], W21 = view_mat[7], W22 = view_mat[8];

    float eye_x = cam_eye[0], eye_y = cam_eye[1], eye_z = cam_eye[2];

    float O00 = obj_mat[0], O01 = obj_mat[1], O02 = obj_mat[2], O03 = obj_mat[3];
    float O10 = obj_mat[4], O11 = obj_mat[5], O12 = obj_mat[6], O13 = obj_mat[7];
    float O20 = obj_mat[8], O21 = obj_mat[9], O22 = obj_mat[10], O23 = obj_mat[11];
    int has_obj_xform = (O00 != 1.0f || O11 != 1.0f || O22 != 1.0f ||
                         O01 != 0.0f || O02 != 0.0f || O10 != 0.0f ||
                         O12 != 0.0f || O20 != 0.0f || O21 != 0.0f ||
                         O03 != 0.0f || O13 != 0.0f || O23 != 0.0f);

    int has_clip = (clip_plane != NULL);
    float c_nx = 0.0f, c_ny = 0.0f, c_nz = 0.0f, c_d = 0.0f;
    if (has_clip) {
        c_nx = clip_plane[0];
        c_ny = clip_plane[1];
        c_nz = clip_plane[2];
        c_d = clip_plane[3];
    }

    int r = point_size / 2;
    int r_sq = (int)((r + 0.5f) * (r + 0.5f));

    int chunk_size = 32768;
    int n_chunks = (n_points + chunk_size - 1) / chunk_size;
    dispatch_queue_t queue = dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_HIGH, 0);

    dispatch_apply(n_chunks, queue, ^(size_t chunk_idx) {
        int start = (int)chunk_idx * chunk_size;
        int end = start + chunk_size;
        if (end > n_points) end = n_points;

        for (int i = start; i < end; i++) {
            float x = coords[i * 3 + 0];
            float y = coords[i * 3 + 1];
            float z_w = coords[i * 3 + 2];
            float wx = x, wy = y, wz = z_w;
            if (has_obj_xform) {
                wx = O00 * x + O01 * y + O02 * z_w + O03;
                wy = O10 * x + O11 * y + O12 * z_w + O13;
                wz = O20 * x + O21 * y + O22 * z_w + O23;
            }

            // Section plane clipping
            if (has_clip) {
                float dist = c_nx * wx + c_ny * wy + c_nz * wz + c_d;
                if (dist < 0.0f) continue;
            }

            float dx_eye = wx - eye_x;
            float dy_eye = wy - eye_y;
            float dz_eye = wz - eye_z;
            float c_x = W00 * dx_eye + W01 * dy_eye + W02 * dz_eye;
            float c_y = W10 * dx_eye + W11 * dy_eye + W12 * dz_eye;
            float c_z = W20 * dx_eye + W21 * dy_eye + W22 * dz_eye;

            float z = -c_z;
            int px, py;
            uint32_t z_int;

            if (is_ortho) {
                // Parallel / Orthographic (Top, Front, Right, Iso, etc.)
                px = (int)(fx * c_x + cx + 0.5f);
                py = (int)(-fy * c_y + cy + 0.5f);
                float d_val = (z + 50000.0f) * 1000.0f;
                if (d_val < 0.0f) d_val = 0.0f;
                if (d_val > 2147483647.0f) d_val = 2147483647.0f;
                z_int = (uint32_t)d_val;
            } else {
                // Perspective
                if (z <= 0.1f) continue;
                float inv_z = 1.0f / z;
                px = (int)(fx * (c_x * inv_z) + cx + 0.5f);
                py = (int)(-fy * (c_y * inv_z) + cy + 0.5f);
                z_int = (uint32_t)(z * 1000.0f);
                if (z_int > 0x7FFFFFFF) z_int = 0x7FFFFFFF;
            }

            if (px < 0 || px >= width || py < 0 || py >= height) continue;

            const uint8_t *src = &colors[i * 4];
            uint8_t r_col = src[0], g_col = src[1], b_col = src[2], a_col = src[3];
            if (opacity_mul < 0.99f) {
                a_col = (uint8_t)(a_col * opacity_mul);
            }
            if (a_col < 5) continue;

            uint32_t pix32 = ((uint32_t)255 << 24) | ((uint32_t)r_col << 16) | ((uint32_t)g_col << 8) | (uint32_t)b_col;

            if (point_size <= 1) {
                int idx = py * width + px;
                uint32_t prev = __atomic_load_n(&depth_buf[idx], __ATOMIC_RELAXED);
                if (z_int < prev) {
                    if (__atomic_compare_exchange_n(&depth_buf[idx], &prev, z_int, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {
                        cbuf32[idx] = pix32;
                    }
                }
            } else {
                int y0 = py - r; if (y0 < 0) y0 = 0;
                int y1 = py + r; if (y1 >= height) y1 = height - 1;
                int x0 = px - r; if (x0 < 0) x0 = 0;
                int x1 = px + r; if (x1 >= width) x1 = width - 1;

                for (int y = y0; y <= y1; y++) {
                    int dy = y - py;
                    int dy_sq = dy * dy;
                    int row_offset = y * width;
                    for (int xp = x0; xp <= x1; xp++) {
                        int dx = xp - px;
                        if (dx * dx + dy_sq <= r_sq) {
                            int idx = row_offset + xp;
                            uint32_t prev = __atomic_load_n(&depth_buf[idx], __ATOMIC_RELAXED);
                            if (z_int < prev) {
                                if (__atomic_compare_exchange_n(&depth_buf[idx], &prev, z_int, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {
                                    cbuf32[idx] = pix32;
                                }
                            }
                        }
                    }
                }
            }
        }
    });

    free(depth_buf);
}
