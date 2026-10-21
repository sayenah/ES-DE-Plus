//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchPresentation.h
//
//  Written for ES-DE-Plus. Search-only observation at the normal frame boundary.
//
#ifndef ES_APP_SEARCH_PRESENTATION_H
#define ES_APP_SEARCH_PRESENTATION_H

#include <functional>

class Renderer;
namespace SearchPresentation
{
    void swap(Renderer& renderer);
    void observe(std::function<void(double, double)> callback);
    void afterFrame(std::function<void()> callback);
} // namespace SearchPresentation

#endif // ES_APP_SEARCH_PRESENTATION_H
