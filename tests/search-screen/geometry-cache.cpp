//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  geometry-cache.cpp
//
//  Written for ES-DE-Plus. Verify cached clipping/panels, bounded invalidation,
//  compact attribute data and public cache color updates against production methods.
//
#include "search/SearchDrawing.h"
#include <cstdlib>
#include <iostream>

#include "font-cache-color.inc"

int main()
{
    int checks {0};
    auto require = [&](bool condition) {
        if (!condition)
            std::abort();
        ++checks;
    };
    unsigned int texture {1};
    TextCache source;
    Renderer::Vertex tl {{0, 0}, {0, 0}, 0x12345678}, bl {{0, 10}, {0, 1}, tl.color};
    Renderer::Vertex tr {{10, 0}, {1, 0}, tl.color}, br {{10, 10}, {1, 1}, tl.color};
    source.getVertexLists().push_back({{tl, tl, bl, tr, br, br}, &texture});
    SearchDrawing::Cache cache;
    auto append = [&](const std::string& value, const void* font, glm::vec2 size, int align,
                      glm::vec2 offset, glm::vec4 clip, unsigned int color) {
        TextCache output;
        cache.append(output, source, value, font, size, align, offset, clip, color);
        return output;
    };
    const void* font = &texture;
    const glm::vec2 size {10, 10}, offset {20, 30};
    const glm::vec4 clip {22, 33, 4, 5};
    auto first = append("test", font, size, 0, offset, clip, 0x12345678);
    auto same = append("test", font, size, 0, offset, clip, 0x12345678);
    require(cache.textEntries() == 1 && first.getVertexLists().size() == 1);
    require(same.getVertexLists()[0].verts.size() == 6);
    for (size_t i {0}; i < 6; ++i) {
        const auto& a = first.getVertexLists()[0].verts[i];
        const auto& b = same.getVertexLists()[0].verts[i];
        require(a.position == b.position && a.texcoord == b.texcoord && a.color == b.color);
    }
    require(first.getVertexLists()[0].verts[1].position == glm::vec2(22, 33));
    require(first.getVertexLists()[0].verts[4].position == glm::vec2(26, 38));
    append("changed", font, size, 0, offset, clip, 0x12345678);
    append("test", &source, size, 0, offset, clip, 0x12345678);
    append("test", font, {20, 10}, 0, offset, clip, 0x12345678);
    append("test", font, size, 1, offset, clip, 0x12345678);
    append("test", font, size, 0, {21, 30}, clip, 0x12345678);
    append("test", font, size, 0, offset, {22, 33, 3, 5}, 0x12345678);
    const auto colored = append("test", font, size, 0, offset, clip, 0xFFFFFFFF);
    require(cache.textEntries() == 8);
    require(colored.getVertexLists()[0].verts[1].color == 0xFFFFFFFF);
    SearchDrawing::pack(first);
    require(sizeof(Renderer::VertexAttributes) < sizeof(Renderer::Vertex));
    require(first.getVertexLists()[0].attributes.size() == 6);
    for (size_t i {0}; i < 6; ++i) {
        const auto& vertex = first.getVertexLists()[0].verts[i];
        const auto& attribute = first.getVertexLists()[0].attributes[i];
        require(vertex.position == attribute.position && vertex.texcoord == attribute.texcoord &&
                vertex.color == attribute.color);
    }
    first.setColor(0xABCDEF80);
    for (size_t i {0}; i < 6; ++i)
        require(first.getVertexLists()[0].verts[i].color == 0xABCDEF80 &&
                first.getVertexLists()[0].attributes[i].color == 0xABCDEF80);
    std::vector<Renderer::Vertex> panel, again;
    cache.panel(panel, {10, 20, 30, 40}, 3, 0x112233FF);
    cache.panel(again, {10, 20, 30, 40}, 3, 0x112233FF);
    require(cache.panelEntries() == 1 && panel.size() == 28 && panel.size() == again.size());
    for (size_t i {0}; i < panel.size(); ++i)
        require(panel[i].position == again[i].position && panel[i].color == again[i].color);
    cache.panel(again, {10, 20, 30, 40}, 3, 0x112233FF);
    require(again.size() == panel.size() * 2 + 2);
    require(again[27].position == again[28].position && again[29].position == again[30].position);
    cache.panel(panel, {10, 20, 30, 40}, 4, 0x112233FF);
    cache.panel(panel, {10, 20, 30, 40}, 3, 0xFFFFFFFF);
    require(cache.panelEntries() == 3);
    size_t maxText {0}, maxPanels {0};
    for (int i {0}; i < 530; ++i) {
        append(std::to_string(i), font, size, 0, offset, clip, 0x12345678);
        std::vector<Renderer::Vertex> batch;
        cache.panel(batch, {static_cast<float>(i), 0, 30, 40}, 3, 0x112233FF);
        maxText = std::max(maxText, cache.textEntries());
        maxPanels = std::max(maxPanels, cache.panelEntries());
    }
    require(maxText <= 512 && maxPanels <= 512 && cache.textEntries() && cache.panelEntries());
    cache.clear();
    require(!cache.textEntries() && !cache.panelEntries());
    std::cout << "PASS: " << checks << " production geometry cache/attribute checks\n";
}
