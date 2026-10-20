//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  main.cpp
//
//  Written for ES-DE-Plus. Independent renderer fixtures and gesture regressions.
//

#include "InputOverlayModel.h"
#include "TouchOverlayReset.h"
#include "layout_baseline.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <new>
#include <random>

static unsigned long allocations {0};
void* operator new(std::size_t size)
{
    ++allocations;
    if (void* p = std::malloc(size ? size : 1))
        return p;
    throw std::bad_alloc {};
}
void* operator new[](std::size_t size) { return ::operator new(size); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }

using namespace TouchOverlay;

static void require(bool pass, const char* message)
{
    if (!pass) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

static Geometry geometry(int w = 1920, int h = 1080, int rotation = 0)
{
    return {static_cast<float>(rotation % 180 ? h : w),
            static_cast<float>(rotation % 180 ? w : h),
            rotation,
            h,
            0,
            0,
            w,
            h,
            w,
            h};
}

struct Oracle {
    std::array<int, 15> held {};
    void accept(const Transitions& transitions)
    {
        require(transitions.count <= 15, "bounded cancellation");
        for (int n {0}; n < transitions.count; ++n) {
            const auto t {transitions.entries[n]};
            int index {-1};
            for (int i {0}; i < 15; ++i)
                if (IDS[i] == t.id)
                    index = i;
            require(index >= 0, "only the fifteen mapped ids");
            require(held[index] != t.value, "press/release alternation");
            held[index] = t.value;
        }
    }
    void empty() const
    {
        for (int value : held)
            require(value == 0, "all accepted holds end");
    }
};

static Point position(const Model& m, int index)
{
    return m.geometry().toNormalized(m.buttons()[index].centre);
}

static void expected(const Transitions& t, std::initializer_list<Transition> values)
{
    require(t.count == static_cast<int>(values.size()), "transition count");
    int i {0};
    for (const auto v : values) {
        require(t.entries[i].id == v.id && t.entries[i].value == v.value, "transition sequence");
        ++i;
    }
}

static void gestures()
{
    Model m;
    m.rebuild(geometry(), Options {}, 320);
    require(m.supported() && !m.compact(), "normal phone layout");
    const Point up {position(m, 0)}, right {position(m, 3)}, a {position(m, 4)}, b {position(m, 5)};
    expected(m.input(Event::DOWN, 1, up), {{11, 1}});
    expected(m.input(Event::MOTION, 1, right), {{11, 0}, {14, 1}});
    m.update(999); // No further event is needed to hold Right.
    require(m.references(3) == 1, "stationary slide holds target");
    expected(m.input(Event::MOTION, 1, right), {});
    expected(m.input(Event::UP, 1, a), {{14, 0}});
    expected(m.input(Event::DOWN, 2, b), {{1, 1}});
    expected(m.input(Event::DOWN, 3, b), {});
    expected(m.input(Event::UP, 2, up), {});
    expected(m.input(Event::UP, 3, up), {{1, 0}});
    expected(m.input(Event::DOWN, 4, a), {{0, 1}});
    m.suppress();
    require(!m.highlighted(4), "legacy suppression hides held art");
    expected(m.input(Event::UP, 4, b), {{0, 0}});
    expected(m.input(Event::DOWN, 4, a), {{0, 1}});
    require(m.highlighted(4), "new gesture clears suppression");
    expected(m.cancel(), {{0, 0}});
    expected(m.input(Event::MOTION, 4, b), {});
    expected(m.input(Event::UP, 4, b), {});
    require(m.tracked() == 0 && !m.highlighted(4), "cancel rejects residual motion and highlight");
    // First importer-block render uses this cancellation path, not suppression.
    expected(m.input(Event::DOWN, 4, up), {{11, 1}});
    expected(m.input(Event::DOWN, 5, position(m, 7)), {{3, 1}});
    const auto epoch {m.epoch()};
    expected(m.cancel(), {{11, 0}, {3, 0}});
    require(m.epoch() != epoch && m.tracked() == 0, "importer boundary starts a fresh epoch");
    expected(m.input(Event::MOTION, 4, right), {});
    expected(m.input(Event::UP, 5, a), {});
    expected(m.input(Event::UP, 4, right), {});
    expected(m.input(Event::DOWN, 4, a), {{0, 1}});
    expected(m.input(Event::DOWN, 4, b), {{0, 0}});
    expected(m.input(Event::MOTION, 4, b), {});
    m.cancel();
    Point empty {0.5f, 0.1f};
    expected(m.input(Event::DOWN, 5, empty), {});
    expected(m.input(Event::MOTION, 5, a), {});
    m.cancel();
    expected(m.input(Event::DOWN, 1, up), {{11, 1}});
    const auto cross {m.input(Event::MOTION, 1, a)};
    for (int n {0}; n < cross.count; ++n)
        require(cross.entries[n].id != 0, "cluster capture");
    m.cancel();
    expected(m.input(Event::DOWN, 1, a), {{0, 1}});
    expected(m.clear(), {{0, 0}});
    m.rebuild(geometry(), Options {}, 320);
    expected(m.input(Event::MOTION, 1, a), {});
    expected(m.input(Event::DOWN, 1, a), {{0, 1}});
    expected(m.rebuild(geometry(1080, 1920), Options {}, 320), {{0, 0}});
    expected(m.input(Event::UP, 1, a), {});
}

static void mapping()
{
    // Independent forward-render fixtures: quarter points are placed by the
    // projection rotation and authoritative viewport, not by toNormalized().
    const std::array<Point, 4> rendered {
        {{0.25f, 0.75f}, {0.25f, 0.25f}, {0.75f, 0.25f}, {0.75f, 0.75f}}};
    for (int i {0}; i < 4; ++i) {
        Geometry g {geometry(800, 600, 90 * i)};
        for (int ox : {-130, 0, 120})
            for (int oy : {-80, 0, 90}) {
                g.viewportX = ox;
                g.viewportY = oy;
                g.windowHeight = 660; // Padding and drawable/window mismatch.
                g.drawableWidth = 900;
                g.drawableHeight = 640;
                const Point input {(ox + rendered[i].x * 800) / 900,
                                   (640 - 660 + oy + rendered[i].y * 600) / 640};
                Point logical;
                require(g.toLogical(input, logical), "independent forward fixture maps");
                require(std::abs(logical.x - 0.25f * g.width) < 0.5f &&
                            std::abs(logical.y - 0.75f * g.height) < 0.5f,
                        "projection fixture accuracy");
                const Point round {g.toNormalized(logical)};
                require(std::abs(round.x - input.x) * 900 < 0.5f &&
                            std::abs(round.y - input.y) * 640 < 0.5f,
                        "mapping round trip");
            }
    }
    Geometry clipped {geometry(1080, 1794)};
    clipped.drawableHeight = 1731;
    const Rect visible {clipped.visible()};
    require(std::abs(visible.y - 63) < 0.01f && std::abs(visible.h - 1731) < 0.01f,
            "G-03 drawable mismatch derives clipped origin");
    Point p;
    require(!clipped.toLogical({NAN, 0}, p), "NaN rejected");
    clipped.drawableHeight = 0;
    require(!clipped.valid() && !clipped.toLogical({}, p), "zero drawable rejected");
    auto edge {geometry(324, 600)};
    edge.viewportX = 13;
    require(std::abs(edge.visible().w - 311) < 0.01f,
            "exact viewport edge survives normalized floating-point rounding");
}

static void boundaries()
{
    Model m;
    m.rebuild(geometry(), Options {}, 320);
    const Point up {position(m, 0)}, a {position(m, 4)};
    const auto& g {m.geometry()};
    const Point pad {m.buttons()[0].centre.x, m.buttons()[2].centre.y};
    expected(m.input(Event::DOWN, 1, g.toNormalized(pad)), {});
    expected(m.input(Event::MOTION, 1, up), {{11, 1}});
    expected(m.input(Event::MOTION, 1, g.toNormalized(pad)), {});
    expected(m.input(Event::UP, 1, {}), {{11, 0}});
    expected(m.input(Event::DOWN, 1, up), {{11, 1}});
    const float r {m.diameter()};
    // -50 degrees remains Up (five degrees beyond the diagonal); -30 switches Right.
    const Point nearBoundary {pad.x + r * std::cos(-50 * 3.14159265f / 180),
                              pad.y + r * std::sin(-50 * 3.14159265f / 180)};
    expected(m.input(Event::MOTION, 1, g.toNormalized(nearBoundary)), {});
    const Point crossed {pad.x + r * std::cos(-30 * 3.14159265f / 180),
                         pad.y + r * std::sin(-30 * 3.14159265f / 180)};
    expected(m.input(Event::MOTION, 1, g.toNormalized(crossed)), {{11, 0}, {14, 1}});
    m.cancel();
    expected(m.input(Event::DOWN, 1, up, true), {{11, 1}});
    expected(m.input(Event::MOTION, 1, position(m, 3), true), {{11, 0}});
    expected(m.input(Event::MOTION, 1, position(m, 3), true), {{14, 1}});
    expected(m.input(Event::UP, 1, {}, true), {{14, 0}});
    expected(m.input(Event::DOWN, 1, a), {{0, 1}});
    const auto faceCentre {m.buttons()[4].centre};
    expected(m.input(Event::MOTION, 1, g.toNormalized({faceCentre.x + 0.1f * r, faceCentre.y})),
             {});
    expected(m.input(Event::MOTION, 1, position(m, 5)), {{0, 0}, {1, 1}});
    expected(m.input(Event::MOTION, 1, {NAN, 0}), {{1, 0}});
    expected(m.input(Event::UP, 1, {}), {});
    const auto pill {m.buttons()[8]};
    expected(m.input(Event::DOWN, 1, position(m, 8)), {{4, 1}});
    expected(
        m.input(Event::MOTION, 1, g.toNormalized({pill.hit.x + pill.hit.w * 1.06f, pill.centre.y})),
        {});
    expected(
        m.input(Event::MOTION, 1, g.toNormalized({pill.hit.x + pill.hit.w * 1.1f, pill.centre.y})),
        {{4, 0}});
    expected(m.input(Event::UP, 1, {}), {});
    // Thirty-two stable IDs, not pointer indices; overflow is inert and bounded.
    expected(m.input(Event::DOWN, 99, a), {{0, 1}});
    for (int i {1}; i < 32; ++i)
        expected(m.input(Event::DOWN, i * 37 + 99, a), {});
    expected(m.input(Event::DOWN, 9999, a), {});
    require(m.tableFull() && m.tracked() == 32 && m.references(4) == 32, "full table bounded");
    for (int i {0}; i < 31; ++i)
        expected(m.input(Event::UP, i * 37 + 99, {}), {});
    expected(m.input(Event::UP, 31 * 37 + 99, {}), {{0, 0}});
    require(m.tracked() == 0, "all lifted fingers forgotten");
    expected(m.input(Event::DOWN, 0, a), {});
    expected(m.input(Event::DOWN, -1, a), {});
    expected(m.input(Event::DOWN, 1, {NAN, 0}), {});
    expected(m.input(Event::MOTION, 1, a), {});
    m.cancel();
    // Invalid/zero geometry cancels a previous press before rejecting all new input.
    expected(m.input(Event::DOWN, 1, a), {{0, 1}});
    Geometry invalid {geometry()};
    invalid.drawableWidth = 0;
    expected(m.rebuild(invalid, Options {}, 320), {{0, 0}});
    expected(m.input(Event::DOWN, 2, a), {});
    m.rebuild(geometry(288, 480), Options {}, 160);
    require(m.compact(), "narrow supported pane uses compact grid");
    for (const auto& button : m.buttons()) {
        // The previous 24 dp side / 32 dp bottom compact corner was only
        // hypot(24,32)=40 dp away, inside the specified 48 dp corner zone.
        for (const Point corner :
             {Point {0, 0}, Point {288, 0}, Point {0, 480}, Point {288, 480}}) {
            const float dx {corner.x -
                            std::clamp(corner.x, button.hit.x, button.hit.x + button.hit.w)};
            const float dy {corner.y -
                            std::clamp(corner.y, button.hit.y, button.hit.y + button.hit.h)};
            require(std::hypot(dx, dy) >= 48, "compact targets avoid conservative corner zones");
        }
    }
    const auto first {m.buttons()[0]};
    const Point edge {first.hit.x + first.hit.w, first.centre.y};
    require(!first.hit.contains(edge) && m.buttons()[1].hit.contains(edge),
            "shared compact edge has exactly one owner");
    expected(m.input(Event::DOWN, 1, m.geometry().toNormalized(edge)), {{12, 1}});
    expected(m.input(Event::UP, 1, {}), {{12, 0}});
    for (int rotation : {0, 90, 180, 270}) {
        auto clipped {geometry(1080, 1794, rotation)};
        clipped.viewportX = -37;
        clipped.viewportY = 25;
        clipped.drawableHeight = 1731;
        m.rebuild(clipped, Options {}, 320);
        require(m.supported(), "clipped viewport supported in every rotation");
        const auto visible {clipped.visible()};
        for (const auto& b : m.buttons()) {
            require(b.hit.x >= visible.x && b.hit.y >= visible.y &&
                        b.hit.x + b.hit.w <= visible.x + visible.w &&
                        b.hit.y + b.hit.h <= visible.y + visible.h,
                    "V-local bounds under clipping");
        }
    }
}

static void layouts()
{
    int cases {0};
    for (Point resolution : {Point {320, 568}, Point {411, 891}, Point {600, 960},
                             Point {800, 1280}, Point {1920, 1080}, Point {288, 288}}) {
        for (bool portrait : {false, true})
            for (float density : {120.0f, 160.0f, 240.0f, 320.0f, 640.0f, 0.0f}) {
                float previous {0};
                for (auto size : {"x-small", "small", "medium", "large"}) {
                    const float scale {density > 0 ? density / 160 : 1};
                    const int w {
                        static_cast<int>((portrait ? resolution.x : resolution.y) * scale)};
                    const int h {
                        static_cast<int>((portrait ? resolution.y : resolution.x) * scale)};
                    Geometry g {geometry(w, h)};
                    Model m;
                    const Options options {Options::parse(size, "normal", 6, false)};
                    m.rebuild(g, options, density);
                    if (!m.supported()) {
                        std::fprintf(stderr, "unsupported %.0fx%.0f dpi=%.0f size=%s\n", g.width,
                                     g.height, density, size);
                        require(false, "supported viewport has fifteen controls");
                    }
                    require(m.diameter() + 0.01f >= previous * 1.1f,
                            "each size grows by at least 10 percent");
                    previous = m.diameter();
                    require(m.diameter() <= 84 * m.density() * options.size + 0.01f,
                            "diameter cap");
                    const Rect safe {m.safeArea()};
                    for (int i {0}; i < 15; ++i) {
                        const Button& b {m.buttons()[i]};
                        if (i < 4) {
                            // Native SVG inner arrow is Left: rotate (-1, 0),
                            // independently of the outer outline's orientation.
                            const float angle {b.rotation * 3.14159265f / 180};
                            const std::array<Point, 4> actions {{{0, -1}, {0, 1}, {-1, 0}, {1, 0}}};
                            require(std::abs(-std::cos(angle) - actions[i].x) < 0.001f &&
                                        std::abs(-std::sin(angle) - actions[i].y) < 0.001f,
                                    "native Left arrow points in action direction in every layout");
                        }
                        else
                            require(b.rotation == 0, "face and pill glyphs stay upright");
                        require(b.hit.w + 0.01f >= 48 * m.density() &&
                                    b.hit.h + 0.01f >= 48 * m.density(),
                                "48 logical dp target floor");
                        require(b.hit.x + 0.01f >= safe.x && b.hit.y + 0.01f >= safe.y &&
                                    b.hit.x + b.hit.w <= safe.x + safe.w + 0.01f &&
                                    b.hit.y + b.hit.h <= safe.y + safe.h + 0.01f,
                                "complete hit bounds safe");
                        for (int j {0}; j < i; ++j) {
                            const auto& a {m.buttons()[j]};
                            if (a.circle && b.circle)
                                require(
                                    std::hypot(a.centre.x - b.centre.x, a.centre.y - b.centre.y) +
                                            0.01f >=
                                        (a.hit.w + b.hit.w) / 2,
                                    "circle activation regions disjoint");
                            else
                                require(a.hit.x + a.hit.w <= b.hit.x + 0.01f ||
                                            b.hit.x + b.hit.w <= a.hit.x + 0.01f ||
                                            a.hit.y + a.hit.h <= b.hit.y + 0.01f ||
                                            b.hit.y + b.hit.h <= a.hit.y + 0.01f,
                                        "rectangle activation regions disjoint");
                        }
                        expected(m.input(Event::DOWN, 1, position(m, i)), {{IDS[i], 1}});
                        expected(m.input(Event::UP, 1, {}), {{IDS[i], 0}});
                    }
                    ++cases;
                }
            }
    }
    Model m;
    m.rebuild(geometry(80, 80), Options {}, 160);
    require(!m.supported(), "unsupported tiny viewport refuses invalid layout");
    m.rebuild(geometry(1080, 1920), Options {}, 320);
    require(std::abs(m.density() - 2) < 0.001f, "logical ddpi used irrespective of physical dpi");
    std::printf("PASS: %d layout/density/size fixtures\n", cases);
}

static void sizeRegressions()
{
    // Sweep the common phone widths from the QA reproduction, including the
    // normal/compact boundary. Logical density changes must preserve each step.
    for (int width {288}; width <= 800; ++width)
        for (int dpi : {120, 160, 420, 640}) {
            const float density {dpi / 160.0f};
            float previous {0};
            for (auto size : {"x-small", "small", "medium", "large"}) {
                Model m;
                m.rebuild(
                    geometry(static_cast<int>(width * density), static_cast<int>(891 * density)),
                    Options::parse(size, "normal", 0, false), dpi);
                require(m.supported(), "phone width sweep supported");
                require(m.diameter() + 0.001f >= previous * 1.1f,
                        "phone sizes remain visibly distinct at every supported width");
                if (width == 411 && std::string {size} == "large")
                    require(m.diameter() / density > 50,
                            "large can exceed the former portrait ceiling while fitting");
                previous = m.diameter();
            }
        }
    std::puts("PASS: distinct sizes at 288..800 dp, four logical densities");
}

static void resetIntentRegressions()
{
    const std::string marker {"touch-reset-test.intent"};
    auto write = [&](const std::string& value) {
        std::ofstream output {marker, std::ios::binary};
        output << value;
    };
    int applied {0};
    auto apply = [&] {
        ++applied;
        return true;
    };
    require(!TouchOverlay::consumeReset(marker, "/selected", apply), "normal startup has no reset");
    write("setup-session\n");
    require(!TouchOverlay::consumeReset(marker, "/selected", apply),
            "uncommitted draft cannot reset");
    write("setup-session\n/selected");
    require(!TouchOverlay::consumeReset(marker, "/other", apply),
            "reset bound to selected data root");
    bool failed {false};
    require(!TouchOverlay::consumeReset(
                marker, "/selected", [] { return false; }, &failed) &&
                failed,
            "failed save retains intent and reports startup failure before user input");
    require(TouchOverlay::consumeReset(marker, "/selected", apply),
            "persisted reset survives process replacement and draft cleanup");
    require(!TouchOverlay::consumeReset(marker, "/selected", apply) && applied == 1,
            "consumed reset cannot enable a subsequently disabled overlay");
    std::puts("PASS: setup intent binding, failed-save retry, fresh-process consume-once reset");
}

static void fittingSetRegressions()
{
    // Narrow bands missed by the 3% scan, plus 2.5..3.3:1 portraits that
    // previously used artwork-only scaling despite a complete real family.
    for (const auto viewport : {Point {316, 1241}, Point {330, 1298}, Point {337, 1326},
                                Point {372, 1139}, Point {372, 1172}, Point {386, 1152}}) {
        float previous {0};
        for (auto size : {"x-small", "small", "medium", "large"}) {
            Model m;
            m.rebuild(geometry(static_cast<int>(viewport.x), static_cast<int>(viewport.y)),
                      Options::parse(size, "normal", 6, false), 160);
            require(m.supported() && !m.compact(),
                    "fine scan preserves narrow normal fitting band");
            require(m.diameter() + 0.01f >= previous * 1.1f,
                    "fitting-set family has 10 percent steps");
            if (viewport.x == 372)
                require(std::abs(m.buttons()[5].centre.x - m.buttons()[6].centre.x -
                                 2.1f * m.diameter()) < 0.02f,
                        "search finds real diameter family before artwork-only fallback");
            previous = m.diameter();
        }
    }
    Model m;
    m.rebuild(geometry(1080, 1920), Options::parse("medium", "normal", 2, false), 420);
    for (const auto& button : m.buttons())
        require(m.claims(m.geometry().toNormalized(button.centre)),
                "overlay claims each rendered control first");
    require(!m.claims({0.5f, 0.1f}), "visible overlay leaves direct GUI gestures unclaimed");
    for (int i {0}; i < 5; ++i)
        m.update(500);
    require(m.claims({0.5f, 0.1f}), "hidden overlay owns complete waking gesture");
    std::puts("PASS: fine fitting bands, real four-diameter families and overlay-first claims");
}

static void normalDeckRegressions()
{
    for (const auto viewport : {Point {800, 1280}, Point {560, 1392}, Point {560, 1369},
                                Point {577, 1392}, Point {564, 1393}, Point {587, 1393}}) {
        for (float density : {0.75f, 1.0f, 2.625f, 4.0f}) {
            float previous {0};
            for (auto size : {"x-small", "small", "medium", "large"}) {
                Model m;
                m.rebuild(geometry(static_cast<int>(std::ceil(viewport.x * density)),
                                   static_cast<int>(std::ceil(viewport.y * density))),
                          Options::parse(size, "normal", 6, false), density * 160);
                require(m.supported() && !m.compact(), "tall portrait keeps normal deck");
                require(m.diameter() + 0.01f >= previous * 1.1f,
                        "tall portrait keeps four distinct sizes");
                previous = m.diameter();
            }
        }
    }
    int cases {0}, normal {0};
    std::size_t run {0};
    unsigned short remaining {NORMAL_LAYOUT_RUNS[0]};
    bool historicalNormal {false};
    for (float density : {0.75f, 1.0f, 1.5f, 2.0f, 2.625f, 2.75f, 3.0f, 3.5f, 4.0f})
        for (int w {288}; w <= 1400; w += 17)
            for (int h {288}; h <= 1400; h += 23)
                for (int rotation : {0, 90}) {
                    float previous {0};
                    for (auto size : {"x-small", "small", "medium", "large"}) {
                        if (!remaining) {
                            require(++run < NORMAL_LAYOUT_RUNS.size(), "baseline covers sweep");
                            remaining = NORMAL_LAYOUT_RUNS[run];
                            historicalNormal = !historicalNormal;
                        }
                        --remaining;
                        Model m;
                        const auto g {geometry(static_cast<int>(std::ceil(w * density)),
                                               static_cast<int>(std::ceil(h * density)), rotation)};
                        const auto options {Options::parse(size, "normal", 6, false)};
                        m.rebuild(g, options, density * 160);
                        require(m.supported(), "full sweep viewport supported");
                        require(!historicalNormal || !m.compact(),
                                "93218fc9e normal deck never regresses to compact");
                        require(m.diameter() + 0.01f >= previous * 1.1f,
                                "full sweep retains four 10 percent steps");
                        require(m.diameter() <= 84 * density * options.size + 0.01f,
                                "full sweep visual cap");
                        previous = m.diameter();
                        for (int i {0}; i < 15; ++i) {
                            const auto& b {m.buttons()[i]};
                            const auto& safe {m.safeArea()};
                            require(b.hit.w + 0.01f >= 48 * density &&
                                        b.hit.h + 0.01f >= 48 * density,
                                    "full sweep 48 dp targets");
                            if (m.compact())
                                require(b.width * 1.08f <= b.hit.w + 0.01f &&
                                            b.height * 1.08f <= b.hit.h + 0.01f,
                                        "compact artwork and underlay stay inside hit cell");
                            require(b.hit.x + 0.01f >= safe.x && b.hit.y + 0.01f >= safe.y &&
                                        b.hit.x + b.hit.w <= safe.x + safe.w + 0.01f &&
                                        b.hit.y + b.hit.h <= safe.y + safe.h + 0.01f,
                                    "full sweep safe bounds");
                            for (int j {0}; j < i; ++j) {
                                const auto& a {m.buttons()[j]};
                                if (a.circle && b.circle)
                                    require(std::hypot(a.centre.x - b.centre.x,
                                                       a.centre.y - b.centre.y) +
                                                    0.01f >=
                                                (a.hit.w + b.hit.w) / 2,
                                            "full sweep disjoint circles");
                                else
                                    require(a.hit.x + a.hit.w <= b.hit.x + 0.01f ||
                                                b.hit.x + b.hit.w <= a.hit.x + 0.01f ||
                                                a.hit.y + a.hit.h <= b.hit.y + 0.01f ||
                                                b.hit.y + b.hit.h <= a.hit.y + 0.01f,
                                            "full sweep disjoint rectangles");
                            }
                            expected(m.input(Event::DOWN, 1, position(m, i)), {{IDS[i], 1}});
                            expected(m.input(Event::UP, 1, {}), {{IDS[i], 0}});
                        }
                        normal += historicalNormal;
                        ++cases;
                    }
                }
    require(cases == 232848 && normal == 223208 && run + 1 == NORMAL_LAYOUT_RUNS.size() &&
                remaining == 0,
            "complete historical oracle consumed");
    std::printf(
        "PASS: %d sweep cases; %d historical normal cases; 0 normal-to-compact regressions\n",
        cases, normal);
}

static void outwardDrift()
{
    Model m;
    m.rebuild(geometry(), Options {}, 320);
    const auto& g {m.geometry()};
    const auto safe {m.safeArea()};
    const float radius {1.05f * m.diameter() + m.buttons()[0].hit.w / 2};
    const Point pad {m.buttons()[0].centre.x, m.buttons()[2].centre.y};
    const Point outsideSafe {safe.x - 0.1f * radius, pad.y};
    require(g.visible().contains(outsideSafe) && !safe.contains(outsideSafe),
            "outward drift fixture is visible but outside conservative safe area");
    expected(m.input(Event::DOWN, 1, g.toNormalized(outsideSafe)), {});
    expected(m.input(Event::UP, 1, {}), {});
    expected(m.input(Event::DOWN, 1, position(m, 2)), {{13, 1}});
    expected(m.input(Event::MOTION, 1, g.toNormalized(outsideSafe)), {});
    require(m.highlighted(2), "held Left keeps full outward hysteresis beyond safe edge");
    expected(m.input(Event::MOTION, 1, g.toNormalized({pad.x + 1.41f * radius, pad.y})), {{13, 0}});
    expected(m.input(Event::UP, 1, {}), {});
}

static void fading()
{
    const Options bad {Options::parse("bogus", "bogus", 99, false)};
    require(bad.size == 1 && bad.opacity == 1 && bad.fadeSeconds == 20 && bad.invalidSize &&
                bad.invalidOpacity && bad.clampedFade,
            "settings fallback/clamps");
    Model m;
    m.rebuild(geometry(), Options::parse("medium", "normal", 2, false), 320);
    for (int i {0}; i < 5; ++i)
        m.update(500);
    require(m.fade() == Fade::HIDDEN, "fade hides after 500ms transition");
    expected(m.input(Event::DOWN, 1, position(m, 4)), {});
    expected(m.input(Event::MOTION, 1, position(m, 5)), {});
    expected(m.input(Event::UP, 1, {}), {});
    expected(m.input(Event::DOWN, 1, position(m, 4)), {{0, 1}});
    m.cancel();
    m.wake(true);
    for (int i {0}; i < 4; ++i)
        m.update(500);
    require(m.fade() == Fade::FADING, "fade boundary");
    expected(m.input(Event::DOWN, 1, position(m, 4)), {{0, 1}});
    m.cancel();
    m.rebuild(geometry(), Options::parse("medium", "normal", 2, true), 320);
    require(m.fade() == Fade::HIDDEN, "TV automatic wake hidden");
    for (int i {0}; i < 60; ++i)
        m.update(500);
    require(m.fade() == Fade::HIDDEN, "TV automatic wake stays hidden across updates");
    m.cancel();
    m.update(16);
    require(m.fade() == Fade::HIDDEN, "cancellation cannot wake a hidden overlay");
    m.wake(true);
    require(m.fade() == Fade::VISIBLE, "TV explicit wake visible");
    m.wake(false);
    require(m.fade() == Fade::HIDDEN, "explicit resume independent of delta time");
    m.rebuild(geometry(), Options::parse("medium", "normal", -5, true), 320);
    for (int i {0}; i < 100; ++i)
        m.update(500);
    require(m.fade() == Fade::VISIBLE, "T=0 remains visible on TV");
}

static void generated()
{
    Model m;
    Oracle oracle;
    std::mt19937 random {0x18A3};
    oracle.accept(m.rebuild(geometry(), Options {}, 320));
    const auto before {allocations};
    // A separate cohort has complete physical gestures, rather than treating
    // arbitrary duplicate DOWN/untracked UP events as valid input.
    std::array<bool, 12> down {};
    for (int n {0}; n < 100000; ++n) {
        const int index {static_cast<int>(random() % down.size())};
        const Event event {!down[index]      ? Event::DOWN :
                           random() % 3 == 0 ? Event::UP :
                                               Event::MOTION};
        const Point point {position(m, random() % 15)};
        const auto transitions {m.input(event, index + 1, point)};
        require(transitions.count <= 2, "bounded valid-gesture transitions");
        oracle.accept(transitions);
        down[index] = event != Event::UP;
        m.update(16);
        if (n % 100 == 99) {
            for (int i {0}; i < static_cast<int>(down.size()); ++i)
                if (down[i])
                    oracle.accept(m.input(Event::UP, i + 1, {}));
            down = {};
            oracle.empty();
            require(m.tracked() == 0, "lifting every valid pointer empties capture table");
        }
    }
    for (int n {0}; n < 100000; ++n) {
        const int id {static_cast<int>(random() % 12 + 1)};
        const int choice {static_cast<int>(random() % 100)};
        Point point {position(m, random() % 15)};
        if (choice < 5)
            point = {NAN, INFINITY};
        else if (choice < 10)
            point = {-2, 3};
        // Fault cohort: duplicate DOWN, missing UP, untracked events and invalid
        // coordinates. Every fault sequence ends in an explicit cancellation.
        if (choice == 0)
            oracle.accept(m.cancel());
        else if (choice == 1) {
            oracle.accept(m.rebuild(geometry(), Options {}, 320));
        }
        else {
            const auto t {m.input(static_cast<Event>(random() % 3), id, point)};
            require(t.count <= 2, "bounded per-event transitions");
            oracle.accept(t);
        }
        for (int i {0}; i < 15; ++i)
            require(m.references(i) >= 0, "nonnegative refcounts");
        m.update(16);
        if (n % 100 == 99)
            oracle.accept(m.cancel());
    }
    oracle.accept(m.cancel());
    oracle.empty();
    require(m.tracked() == 0, "cancellation empties finger table");
    require(before == allocations, "warmed model input/update allocates nothing");
    std::puts(
        "PASS: 100000 valid events + 100000 fault events, epochs, balance and zero allocations");
}

int main()
{
    gestures();
    mapping();
    boundaries();
    layouts();
    sizeRegressions();
    fittingSetRegressions();
    resetIntentRegressions();
    normalDeckRegressions();
    outwardDrift();
    fading();
    generated();
    std::puts("PASS: overlay model deterministic regressions");
}
