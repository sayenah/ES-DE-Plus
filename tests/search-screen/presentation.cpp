//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  presentation.cpp
//
//  Written for ES-DE-Plus. Execute normal-swap ordering, deferred font preparation,
//  the Debug-only cursor observer and actual keystroke classification initialization.
//
#include "search/SearchPresentation.h"
#include <cassert>
#include <chrono>
#include <functional>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

std::vector<std::string> events;
constexpr int LogDebug {1};
class Log
{
public:
    inline static int level {0};
    static int getReportingLevel() { return level; }
};
class Renderer
{
public:
    void swapBuffers() { events.push_back("swap"); }
};
class GuiSearch
{
public:
    inline static int preparations {0};
    static void prepareRenderer()
    {
        if (++preparations <= 3)
            events.push_back("prepare");
    }
    void beginKeystroke();
    bool mMeasureFrame {false}, mKeystrokeFrame {false};
    double mQueryWorkMs {0};
};
#include "begin-keystroke.inc"
#include "presentation.inc"
int main()
{
    Renderer renderer;
    SearchPresentation::swap(renderer);
    if (events != std::vector<std::string> {"swap", "prepare"})
        return 1;
    events.clear();
    SearchPresentation::observe([](double frame, double swap) {
        assert(frame >= swap && swap >= 0);
        events.push_back("observe");
    });
    SearchPresentation::afterFrame([] { events.push_back("disabled cursor"); });
    SearchPresentation::swap(renderer);
    if (events != std::vector<std::string> {"swap", "observe", "prepare"})
        return 1;
    events.clear();
    Log::level = LogDebug;
    SearchPresentation::afterFrame([] { events.push_back("cursor"); });
    assert(events.empty());
    SearchPresentation::swap(renderer);
    if (events != std::vector<std::string> {"swap", "observe", "cursor", "prepare"})
        return 1;
    events.clear();
    SearchPresentation::swap(renderer);
    if (events != std::vector<std::string> {"swap", "observe"})
        return 1;
    events.clear();
    SearchPresentation::observe({});
    SearchPresentation::swap(renderer);
    if (events != std::vector<std::string> {"swap"})
        return 1;
    GuiSearch search;
    search.mMeasureFrame = true; // A pending index-ready refresh is informational.
    search.mQueryWorkMs = 104.5;
    search.beginKeystroke();
    if (!search.mMeasureFrame || !search.mKeystrokeFrame || search.mQueryWorkMs != 0)
        return 1;
    search.mQueryWorkMs = 7;
    search.beginKeystroke(); // Several text commits in one frame preserve their work.
    if (search.mQueryWorkMs != 7)
        return 1;
    std::cout
        << "PASS: production presentation ordering, incremental preparation, cursor ownership "
           "and keystroke cause\n";
}
