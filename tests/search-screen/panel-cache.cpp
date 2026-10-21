//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  panel-cache.cpp
//
//  Written for ES-DE-Plus. Checks the production panel strips without OpenGL.
//

#include "search/SearchDrawing.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace
{
    int checks {0};
    void require(bool value, const char* reason)
    {
        ++checks;
        if (!value) {
            std::fprintf(stderr, "FAIL: panel strips %s\n", reason);
            std::exit(1);
        }
    }
    double area(glm::vec2 a, glm::vec2 b, glm::vec2 c)
    {
        return std::abs((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)) / 2;
    }
    double filledArea(const std::vector<Renderer::Vertex>& batch)
    {
        double result {0};
        for (size_t i {2}; i < batch.size(); ++i) {
            const auto& a = batch[i - 2];
            const auto& b = batch[i - 1];
            const auto& c = batch[i];
            const auto triangle = area(a.position, b.position, c.position);
            if (triangle > 0.000001)
                require(a.color == b.color && b.color == c.color,
                        "no connecting triangle between differently colored panels");
            result += triangle;
        }
        return result;
    }
} // namespace

int main()
{
    std::vector<Renderer::Vertex> batch;
    SearchDrawing::rectangle(batch, {2, 3, 10, 8}, 0x123456FF);
    require(batch.size() == 4 && filledArea(batch) == 80, "rectangle has exact filled area");
    SearchDrawing::rectangle(batch, {100, 90, 5, 4}, 0xABCDEF80);
    require(batch.size() == 10 && filledArea(batch) == 100,
            "separated rectangles have no connecting area");
    for (int sides {3}; sides <= 32; ++sides) {
        std::vector<glm::vec2> outline;
        for (int i {0}; i < sides; ++i) {
            const float angle = static_cast<float>(i) * 6.283185307f / sides;
            outline.push_back({30 + 20 * std::cos(angle), 40 + 15 * std::sin(angle)});
        }
        double expected {0};
        for (size_t i {1}; i + 1 < outline.size(); ++i)
            expected += area(outline[0], outline[i], outline[i + 1]);
        batch.clear();
        SearchDrawing::polygon(batch, outline, 0xFFFFFFFF);
        require(batch.size() == outline.size(), "one vertex per convex corner");
        require(std::abs(filledArea(batch) - expected) < 0.001,
                "convex strip has the same area as an independent fan");
    }
    batch.clear();
    SearchDrawing::polygon(batch, {{0, 0}, {1, 1}}, 0xFFFFFFFF);
    require(batch.empty(), "insufficient corners do not produce geometry");
    std::printf("PASS: %d production panel strip checks\n", checks);
}
