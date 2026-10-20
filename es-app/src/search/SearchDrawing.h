//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchDrawing.h
//
//  Written for ES-DE-Plus. Compact convex panel strips for the search screen.
//

#ifndef ES_APP_SEARCH_DRAWING_H
#define ES_APP_SEARCH_DRAWING_H

#include "renderers/Renderer.h"

#include <vector>

namespace SearchDrawing
{
    inline void polygon(std::vector<Renderer::Vertex>& batch,
                        const std::vector<glm::vec2>& outline,
                        unsigned int color)
    {
        if (outline.size() < 3)
            return;
        if (!batch.empty()) {
            batch.push_back(batch.back());
            batch.emplace_back(outline.front(), glm::vec2 {}, color);
        }
        batch.emplace_back(outline.front(), glm::vec2 {}, color);
        // A convex polygon can be filled by alternating its two outside edges.
        // This uses one vertex per corner instead of six per fan triangle.
        size_t left {1}, right {outline.size() - 1};
        while (left <= right) {
            batch.emplace_back(outline[left++], glm::vec2 {}, color);
            if (left <= right)
                batch.emplace_back(outline[right--], glm::vec2 {}, color);
        }
    }

    inline void rectangle(std::vector<Renderer::Vertex>& batch,
                          const glm::vec4& rect,
                          unsigned int color)
    {
        polygon(batch,
                {{rect.x, rect.y},
                 {rect.x + rect.z, rect.y},
                 {rect.x + rect.z, rect.y + rect.w},
                 {rect.x, rect.y + rect.w}},
                color);
    }
} // namespace SearchDrawing
#endif
