//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  scan.cpp
//
//  Written for ES-DE-Plus. Exact comparison with the exhaustive fine-scan oracle.
//

#include "InputOverlayModel.h"
#undef ES_CORE_INPUT_OVERLAY_MODEL_H
#define TouchOverlay TouchOverlayReference
#include "InputOverlayModel.h"
#undef TouchOverlay

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>

static void check(int w, int h, int rotation, float density, const char* size)
{
    TouchOverlay::Geometry g {static_cast<float>(rotation ? h : w),
                              static_cast<float>(rotation ? w : h),
                              rotation,
                              h,
                              0,
                              0,
                              w,
                              h,
                              w,
                              h};
    TouchOverlayReference::Geometry referenceGeometry {g.width, g.height, rotation, h, 0,
                                                       0,       w,        h,        w, h};
    TouchOverlay::Model model;
    TouchOverlayReference::Model reference;
    model.rebuild(g, TouchOverlay::Options::parse(size, "normal", 6, false), density * 160);
    reference.rebuild(referenceGeometry,
                      TouchOverlayReference::Options::parse(size, "normal", 6, false),
                      density * 160);
    bool identical {model.supported() == reference.supported() &&
                    model.compact() == reference.compact() &&
                    model.diameter() == reference.diameter()};
    for (int i {0}; i < 15; ++i) {
        const auto& a {model.buttons()[i]};
        const auto& b {reference.buttons()[i]};
        identical &= a.id == b.id && a.cluster == b.cluster && a.circle == b.circle &&
                     a.rotation == b.rotation && a.width == b.width && a.height == b.height &&
                     a.centre.x == b.centre.x && a.centre.y == b.centre.y && a.hit.x == b.hit.x &&
                     a.hit.y == b.hit.y && a.hit.w == b.hit.w && a.hit.h == b.hit.h;
    }
    if (!identical) {
        std::fprintf(stderr,
                     "FAIL: exhaustive scan differs at %dx%d rotation=%d density=%g size=%s\n", w,
                     h, rotation, density, size);
        std::exit(1);
    }
}

int main()
{
    int count {0};
    for (float density : {0.75f, 1.0f, 1.5f, 2.0f, 2.625f, 2.75f, 3.0f, 3.5f, 4.0f})
        for (int w {288}; w <= 1400; w += 17)
            for (int h {288}; h <= 1400; h += 23)
                for (int rotation : {0, 90})
                    for (const auto size : {"x-small", "small", "medium", "large"}) {
                        check(static_cast<int>(std::ceil(w * density)),
                              static_cast<int>(std::ceil(h * density)), rotation, density, size);
                        ++count;
                    }
    std::printf("PASS: %d exhaustive-reference sweep cases; every control bit-identical\n", count);
    for (float density : {0.75f, 1.0f, 2.625f, 4.0f})
        for (const auto viewport : {TouchOverlay::Point {316, 1241},
                                    {330, 1298},
                                    {337, 1326},
                                    {372, 1139},
                                    {372, 1172},
                                    {386, 1152}})
            for (const auto size : {"x-small", "small", "medium", "large"})
                check(static_cast<int>(std::ceil(viewport.x * density)),
                      static_cast<int>(std::ceil(viewport.y * density)), 0, density, size);
    std::puts("PASS: LOW-A/LOW-B exhaustive-reference regressions");
}
