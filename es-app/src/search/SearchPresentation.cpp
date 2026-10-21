//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchPresentation.cpp
//
//  Written for ES-DE-Plus. Keep presentation diagnostics, cursor observations and
//  first-frame font preparation out of the upstream renderer's drawing paths.
//
#include "search/SearchPresentation.h"

#include "guis/GuiSearch.h"
#include "renderers/Renderer.h"

#include <chrono>
#include <utility>

namespace
{
    std::function<void(double, double)> observer;
    std::function<void()> pending;
    std::chrono::steady_clock::time_point previous;
} // namespace

void SearchPresentation::observe(std::function<void(double, double)> callback)
{
    observer = std::move(callback);
    previous = std::chrono::steady_clock::now();
}

void SearchPresentation::afterFrame(std::function<void()> callback)
{
#if !defined(NDEBUG)
    pending = std::move(callback);
#else
    (void)callback;
#endif
}

void SearchPresentation::swap(Renderer& renderer)
{
    const auto started = std::chrono::steady_clock::now();
    renderer.swapBuffers();
    const auto now = std::chrono::steady_clock::now();
    if (observer) {
        const auto interval = std::chrono::duration<double, std::milli>(now - previous).count();
        previous = now;
        observer(interval, std::chrono::duration<double, std::milli>(now - started).count());
    }
    if (pending) {
        auto callback = std::move(pending);
        pending = {};
        callback();
    }
    // The normal frontend has presented its first frame and startup is complete.
    // Preparation cannot add work to preload or delay that initial presentation.
    static bool prepared {false};
    if (!prepared) {
        prepared = true;
        GuiSearch::prepareRenderer();
    }
}
