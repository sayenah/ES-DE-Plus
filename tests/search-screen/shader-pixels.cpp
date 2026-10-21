//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  shader-pixels.cpp
//
//  Written for ES-DE-Plus. Compile the inherited core shader and independent material oracle and
//  compare their framebuffer pixels for the clipped search text/panel subset.
//
#define SDL_MAIN_HANDLED
#define GL_GLEXT_PROTOTYPES
#define GL_SILENCE_DEPRECATION
#include <SDL2/SDL.h>
#include <SDL2/SDL_opengl.h>
#if defined(__APPLE__)
#include <OpenGL/OpenGL.h>
#endif
#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

std::string read(const char* path)
{
    std::ifstream stream {path};
    if (!stream)
        throw std::runtime_error("shader source missing");
    return {std::istreambuf_iterator<char> {stream}, {}};
}
GLuint compile(GLenum type, const std::string& source)
{
    const auto shader = glCreateShader(type);
    const char* text = source.c_str();
    glShaderSource(shader, 1, &text, nullptr);
    glCompileShader(shader);
    GLint good {0};
    glGetShaderiv(shader, GL_COMPILE_STATUS, &good);
    if (!good) {
        std::array<char, 8192> error {};
        glGetShaderInfoLog(shader, error.size(), nullptr, error.data());
        throw std::runtime_error(error.data());
    }
    return shader;
}
GLuint program(const std::string& source, bool gles)
{
    const std::string version = gles ? "#version 300 es\n" : "#version 330\n";
    const auto vertex = compile(GL_VERTEX_SHADER, version + "#define VERTEX\n" + source);
    const auto fragment = compile(GL_FRAGMENT_SHADER, version + "#define FRAGMENT\n" + source);
    const auto result = glCreateProgram();
    glAttachShader(result, vertex);
    glAttachShader(result, fragment);
    glLinkProgram(result);
    GLint good {0};
    glGetProgramiv(result, GL_LINK_STATUS, &good);
    if (!good) {
        std::array<char, 8192> error {};
        glGetProgramInfoLog(result, error.size(), nullptr, error.data());
        throw std::runtime_error(error.data());
    }
    glDeleteShader(vertex);
    glDeleteShader(fragment);
    return result;
}
struct Vertex {
    float x, y, u, v;
    uint32_t color;
};
constexpr int width {96}, height {64};
std::vector<uint8_t> render(
    GLuint shader, GLuint texture, unsigned int flags, float opacity, bool blend)
{
    const std::array<Vertex, 4> vertices {{{-.85f, -.75f, 0, 0, 0xF0802080},
                                           {-.85f, .75f, 0, 1, 0x20C0E0FF},
                                           {.85f, -.75f, 1, 0, 0x8040C0A0},
                                           {.85f, .75f, 1, 1, 0xC0E040C0}}};
    glUseProgram(shader);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices.data(), GL_DYNAMIC_DRAW);
    for (const auto& attribute : std::array<std::pair<const char*, size_t>, 3> {
             {{"positionVertex", 0}, {"texCoordVertex", 8}, {"colorVertex", 16}}}) {
        const auto location = glGetAttribLocation(shader, attribute.first);
        if (location < 0)
            throw std::runtime_error("missing shader attribute");
        glEnableVertexAttribArray(location);
        const bool color = attribute.second == 16;
        glVertexAttribPointer(location, color ? 4 : 2, color ? GL_UNSIGNED_BYTE : GL_FLOAT,
                              color ? GL_TRUE : GL_FALSE, sizeof(Vertex),
                              reinterpret_cast<const void*>(attribute.second));
    }
    const std::array<float, 16> identity {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    glUniformMatrix4fv(glGetUniformLocation(shader, "MVPMatrix"), 1, GL_FALSE, identity.data());
    glUniform1i(glGetUniformLocation(shader, "textureSampler0"), 0);
    glUniform1ui(glGetUniformLocation(shader, "shaderFlags"), flags);
    glUniform1f(glGetUniformLocation(shader, "opacity"), opacity);
    glUniform1f(glGetUniformLocation(shader, "brightness"), 0);
    glUniform1f(glGetUniformLocation(shader, "saturation"), 1);
    glUniform1f(glGetUniformLocation(shader, "dimming"), 1);
    glUniform1f(glGetUniformLocation(shader, "cornerRadius"), 0);
    glUniform1f(glGetUniformLocation(shader, "reflectionsFalloff"), 0);
    glUniform4f(glGetUniformLocation(shader, "clipRegion"), 0, 0, 0, 0);
    glUniform2f(glGetUniformLocation(shader, "texSize"), 32, 32);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, texture);
    glClearColor(.07f, .09f, .13f, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glEnable(GL_BLEND);
    glBlendFunc(blend ? GL_SRC_ALPHA : GL_ONE, blend ? GL_ONE_MINUS_SRC_ALPHA : GL_ZERO);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    std::vector<uint8_t> pixels(width * height * 4);
    glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
    if (glGetError() != GL_NO_ERROR)
        throw std::runtime_error("GL error in actual pixel comparison");
    return pixels;
}
int main(int argc, char** argv)
{
    try {
        const bool gles = argc == 4 && std::string(argv[3]) == "gles";
        if (argc != 3 && !gles)
            throw std::runtime_error("expected core/search shader paths [gles]");
#if defined(__APPLE__)
        if (gles)
            throw std::runtime_error("GLES comparison requires the Linux offscreen driver");
        CGLPixelFormatAttribute format[] {
            kCGLPFAOpenGLProfile, static_cast<CGLPixelFormatAttribute>(kCGLOGLPVersion_3_2_Core),
            kCGLPFAAllowOfflineRenderers, static_cast<CGLPixelFormatAttribute>(0)};
        CGLPixelFormatObj pixelFormat {nullptr};
        GLint formats {0};
        if (CGLChoosePixelFormat(format, &pixelFormat, &formats) != kCGLNoError || !pixelFormat)
            throw std::runtime_error("CGL offscreen pixel format unavailable");
        CGLContextObj context {nullptr};
        const auto created = CGLCreateContext(pixelFormat, nullptr, &context);
        CGLDestroyPixelFormat(pixelFormat);
        if (created != kCGLNoError || !context || CGLSetCurrentContext(context) != kCGLNoError)
            throw std::runtime_error("CGL offscreen context unavailable");
#else
        SDL_SetMainReady();
        if (SDL_Init(SDL_INIT_VIDEO))
            throw std::runtime_error(SDL_GetError());
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, gles ? 0 : 3);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,
                            gles ? SDL_GL_CONTEXT_PROFILE_ES : SDL_GL_CONTEXT_PROFILE_CORE);
        auto* window = SDL_CreateWindow("shader pixels", 0, 0, width, height,
                                        SDL_WINDOW_OPENGL | SDL_WINDOW_HIDDEN);
        if (!window)
            throw std::runtime_error(SDL_GetError());
        auto context = SDL_GL_CreateContext(window);
        if (!context)
            throw std::runtime_error(SDL_GetError());
#endif
        const auto core = program(read(argv[1]), gles), search = program(read(argv[2]), gles);
        GLuint buffer {0}, array {0}, framebuffer {0}, target {0};
        glGenBuffers(1, &buffer);
        glBindBuffer(GL_ARRAY_BUFFER, buffer);
        glGenVertexArrays(1, &array);
        glBindVertexArray(array);
        glGenTextures(1, &target);
        glBindTexture(GL_TEXTURE_2D, target);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE,
                     nullptr);
        glGenFramebuffers(1, &framebuffer);
        glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, target, 0);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
            throw std::runtime_error("FBO incomplete");
        glViewport(0, 0, width, height);
        std::array<GLuint, 2> textures {};
        glGenTextures(2, textures.data());
        for (int mode = 0; mode < 2; ++mode) {
            glBindTexture(GL_TEXTURE_2D, textures[mode]);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
            std::vector<uint8_t> data(mode ? 256 : 4, 255);
            if (mode)
                for (size_t i = 0; i < data.size(); ++i)
                    data[i] = static_cast<uint8_t>(i);
            glTexImage2D(GL_TEXTURE_2D, 0, mode ? GL_R8 : GL_RGBA8, mode ? 16 : 1, mode ? 16 : 1, 0,
                         mode ? GL_RED : GL_RGBA, GL_UNSIGNED_BYTE, data.data());
        }
        size_t cases {0}, samples {0};
        for (unsigned int mode : {0U, 2U})
            for (float opacity : {1.f, .63f})
                for (bool blend : {false, true}) {
                    const auto before = render(core, textures[mode ? 1 : 0], mode, opacity, blend);
                    const auto after = render(search, textures[mode ? 1 : 0], mode, opacity, blend);
                    for (size_t i = 0; i < before.size(); ++i) {
                        if (std::abs(int(before[i]) - int(after[i])) > 1)
                            throw std::runtime_error("search shader pixel mismatch");
                        ++samples;
                    }
                    ++cases;
                }
        std::cout << "PASS: " << cases << " actual shader modes; " << samples
                  << " framebuffer channel comparisons; " << (gles ? "GLES" : "desktop")
                  << " renderer=" << glGetString(GL_RENDERER) << "\n";
        glDeleteProgram(core);
        glDeleteProgram(search);
        glDeleteBuffers(1, &buffer);
        glDeleteVertexArrays(1, &array);
        glDeleteTextures(2, textures.data());
        glDeleteTextures(1, &target);
        glDeleteFramebuffers(1, &framebuffer);
#if defined(__APPLE__)
        CGLSetCurrentContext(nullptr);
        CGLDestroyContext(context);
#else
        SDL_GL_DeleteContext(context);
        SDL_DestroyWindow(window);
        SDL_Quit();
#endif
    }
    catch (const std::exception& error) {
        std::cerr << error.what() << "\n";
        return 1;
    }
}
