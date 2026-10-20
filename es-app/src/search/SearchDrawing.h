//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  SearchDrawing.h
//
//  Written for ES-DE-Plus. Compact convex panel strips for the search screen.
//

#ifndef ES_APP_SEARCH_DRAWING_H
#define ES_APP_SEARCH_DRAWING_H

#include "resources/Font.h"

#include <algorithm>
#include <optional>
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
    inline void appendClipped(TextCache& target,
                              const TextCache& source,
                              const glm::vec2& offset,
                              const glm::vec4& clip,
                              std::optional<unsigned int> color = std::nullopt)
    {
        for (const auto& list : source.getVertexLists()) {
            auto output = std::find_if(
                target.getVertexLists().begin(), target.getVertexLists().end(),
                [&](const auto& item) { return item.textureIdPtr == list.textureIdPtr; });
            if (output == target.getVertexLists().end()) {
                target.getVertexLists().push_back({{}, list.textureIdPtr});
                output = target.getVertexLists().end() - 1;
            }
            for (size_t at {0}; at + 5 < list.verts.size(); at += 6) {
                auto topLeft = list.verts[at + 1];
                auto bottomRight = list.verts[at + 4];
                if (color) {
                    topLeft.color = *color;
                    bottomRight.color = *color;
                }
                topLeft.position += offset;
                bottomRight.position += offset;
                const glm::vec2 low = glm::max(topLeft.position, glm::vec2 {clip.x, clip.y});
                const glm::vec2 high =
                    glm::min(bottomRight.position, glm::vec2 {clip.x + clip.z, clip.y + clip.w});
                if (low.x >= high.x || low.y >= high.y)
                    continue;
                const auto extent = bottomRight.position - topLeft.position;
                const auto uv = bottomRight.texcoord - topLeft.texcoord;
                const auto uvLow = topLeft.texcoord + (low - topLeft.position) / extent * uv;
                const auto uvHigh = topLeft.texcoord + (high - topLeft.position) / extent * uv;
                topLeft.position = low;
                topLeft.texcoord = uvLow;
                bottomRight.position = high;
                bottomRight.texcoord = uvHigh;
                auto bottomLeft = topLeft;
                bottomLeft.position.y = high.y;
                bottomLeft.texcoord.y = uvHigh.y;
                auto topRight = topLeft;
                topRight.position.x = high.x;
                topRight.texcoord.x = uvHigh.x;
                output->verts.insert(output->verts.end(), {topLeft, topLeft, bottomLeft, topRight,
                                                           bottomRight, bottomRight});
            }
            if (output->verts.empty())
                target.getVertexLists().erase(output);
        }
    }

} // namespace SearchDrawing
#endif
