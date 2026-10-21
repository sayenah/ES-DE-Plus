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
#include <cmath>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

namespace SearchDrawing
{
    inline std::vector<Renderer::VertexAttributes> attributes(
        const std::vector<Renderer::Vertex>& vertices)
    {
        std::vector<Renderer::VertexAttributes> result;
        result.reserve(vertices.size());
        for (const auto& vertex : vertices)
            result.push_back({vertex.position, vertex.texcoord, vertex.color});
        return result;
    }
    inline void pack(TextCache& cache)
    {
        for (auto& list : cache.getVertexLists()) {
            if (!list.verts.empty())
                list.verts[0].shaders = Renderer::Shader::SEARCH;
            list.attributes = attributes(list.verts);
        }
    }

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

    // Keep unchanged label/panel geometry when only the query, suggestions or results change.
    class Cache
    {
    public:
        void clear()
        {
            mText.clear();
            mPanels.clear();
        }
        void append(TextCache& target,
                    const TextCache& source,
                    const std::string& value,
                    const void* font,
                    const glm::vec2& size,
                    int alignment,
                    const glm::vec2& offset,
                    const glm::vec4& clip,
                    unsigned int color)
        {
            const TextKey key {reinterpret_cast<uintptr_t>(font),
                               value,
                               size.x,
                               size.y,
                               alignment,
                               offset.x,
                               offset.y,
                               clip.x,
                               clip.y,
                               clip.z,
                               clip.w,
                               color};
            auto found = mText.find(key);
            if (found == mText.end()) {
                if (mText.size() >= 512)
                    mText.clear();
                found = mText.emplace(key, TextCache {}).first;
                appendClipped(found->second, source, offset, clip, color);
            }
            for (const auto& list : found->second.getVertexLists()) {
                auto& lists = target.getVertexLists();
                auto output = std::find_if(lists.begin(), lists.end(), [&](const auto& item) {
                    return item.textureIdPtr == list.textureIdPtr;
                });
                if (output == lists.end()) {
                    lists.push_back({{}, list.textureIdPtr});
                    output = lists.end() - 1;
                }
                output->verts.insert(output->verts.end(), list.verts.begin(), list.verts.end());
            }
        }
        void panel(std::vector<Renderer::Vertex>& target,
                   const glm::vec4& rect,
                   float radius,
                   unsigned int color)
        {
            const PanelKey key {rect.x, rect.y, rect.z, rect.w, radius, color};
            auto found = mPanels.find(key);
            if (found == mPanels.end()) {
                if (mPanels.size() >= 512)
                    mPanels.clear();
                found = mPanels.emplace(key, std::vector<Renderer::Vertex> {}).first;
                std::vector<glm::vec2> outline;
                outline.reserve(28);
                for (int corner {0}; corner < 4; ++corner) {
                    const glm::vec2 origin {
                        corner == 0 || corner == 3 ? rect.x + radius : rect.x + rect.z - radius,
                        corner < 2 ? rect.y + radius : rect.y + rect.w - radius};
                    for (int step {0}; step <= 6; ++step) {
                        const float angle = (180 + corner * 90 + step * 15) * 3.14159265f / 180;
                        outline.push_back(origin +
                                          radius * glm::vec2 {std::cos(angle), std::sin(angle)});
                    }
                }
                polygon(found->second, outline, color);
            }
            if (!target.empty() && !found->second.empty()) {
                target.push_back(target.back());
                target.push_back(found->second.front());
            }
            target.insert(target.end(), found->second.begin(), found->second.end());
        }
        size_t textEntries() const { return mText.size(); }
        size_t panelEntries() const { return mPanels.size(); }

    private:
        using TextKey = std::tuple<uintptr_t,
                                   std::string,
                                   float,
                                   float,
                                   int,
                                   float,
                                   float,
                                   float,
                                   float,
                                   float,
                                   float,
                                   unsigned int>;
        using PanelKey = std::tuple<float, float, float, float, float, unsigned int>;
        std::map<TextKey, TextCache> mText;
        std::map<PanelKey, std::vector<Renderer::Vertex>> mPanels;
    };

} // namespace SearchDrawing
#endif
