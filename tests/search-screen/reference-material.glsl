//  SPDX-License-Identifier: MIT
//
//  ES-DE-Plus
//  search.glsl
//
//  Written for ES-DE-Plus. CPU-clipped search glyphs and flat panels only.
//  Uses the inherited MIT core shader's vertex and color conventions.
//

#if defined(VERTEX)
uniform mat4 MVPMatrix;
in vec2 positionVertex;
in vec2 texCoordVertex;
in vec4 colorVertex;
out vec2 texCoord;
out vec4 color;

void main()
{
    gl_Position = MVPMatrix * vec4(positionVertex, 0.0, 1.0);
    texCoord = texCoordVertex;
    color = colorVertex.abgr;
}
#elif defined(FRAGMENT)
#ifdef GL_ES
precision highp float;
#endif
in vec2 texCoord;
in vec4 color;
uniform sampler2D textureSampler0;
uniform uint shaderFlags;
uniform float opacity;
out vec4 FragColor;

void main()
{
    FragColor = color;
    if ((shaderFlags & 0x2u) != 0u)
        FragColor.a *= texture(textureSampler0, texCoord).r;
    FragColor.a *= opacity;
}
#endif
