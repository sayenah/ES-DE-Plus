//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  text-cache.cpp
//
//  Written for ES-DE-Plus. Tests the production clipping method without an OpenGL context.
//

#include "resources/Font.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>

#include "text-cache.inc"

namespace
{
    void require(bool condition, const char* message)
    {
        if (!condition) {
            std::fprintf(stderr, "FAIL: text cache %s\n", message);
            std::exit(1);
        }
    }
    struct Cache : TextCache {
        void seed(unsigned int* texture, float width = 10)
        {
            Renderer::Vertex top {{0, 0}, {0, 0}, 0x12345678};
            Renderer::Vertex left {{0, 10}, {0, 1}, top.color};
            Renderer::Vertex right {{width, 0}, {1, 0}, top.color};
            Renderer::Vertex bottom {{width, 10}, {1, 1}, top.color};
            vertexLists.push_back({{top, top, left, right, bottom, bottom}, texture});
        }
        size_t batches() const { return vertexLists.size(); }
        size_t vertices(size_t batch = 0) const { return vertexLists.at(batch).verts.size(); }
        const Renderer::Vertex& at(size_t index) const { return vertexLists.at(0).verts.at(index); }
    };
    bool close(float a, float b) { return std::abs(a - b) < 0.0001f; }
} // namespace

int main()
{
    unsigned int texture {1}, fallbackTexture {2};
    Cache source, fallback, output, clipped, degenerate;
    source.seed(&texture);
    fallback.seed(&fallbackTexture);
    output.appendClipped(source, {20, 30}, {22, 33, 4, 5});
    require(output.batches() == 1 && output.vertices() == 6, "one nonempty triangle strip");
    require(output.at(1).position == glm::vec2 {22, 33} &&
                output.at(4).position == glm::vec2 {26, 38},
            "offset and all four clipping edges");
    require(close(output.at(1).texcoord.x, 0.2f) && close(output.at(1).texcoord.y, 0.3f) &&
                close(output.at(4).texcoord.x, 0.6f) && close(output.at(4).texcoord.y, 0.8f),
            "clipping interpolates texture coordinates");
    require(output.at(1).color == 0x12345678 && output.at(4).color == 0x12345678,
            "shaped glyph colors survive composition");
    require(output.at(0).position == output.at(1).position &&
                output.at(5).position == output.at(4).position,
            "degenerate strip boundaries survive clipping");
    output.appendClipped(source, {}, {0, 0, 10, 10});
    require(output.batches() == 1 && output.vertices() == 12, "shared atlas batches together");
    output.appendClipped(fallback, {}, {50, 50, 10, 10});
    require(output.batches() == 1 && output.vertices() == 12,
            "fully clipped fallback atlas never creates an empty draw");
    output.appendClipped(fallback, {}, {0, 0, 10, 10});
    require(output.batches() == 2 && output.vertices(1) == 6, "visible fallback atlas retained");
    clipped.appendClipped(source, {}, {50, 50, 10, 10});
    require(clipped.batches() == 0, "fully clipped first run leaves no draw list");
    degenerate.seed(&texture, 0);
    clipped.appendClipped(degenerate, {}, {0, 0, 10, 10});
    require(clipped.batches() == 0, "zero-area glyph never divides by zero");
    std::puts("PASS: 10 production text-cache clipping/batching checks");
}
