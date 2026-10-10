#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ES-DE-Plus — written for ES-DE-Plus. CI PDF fixtures, generated with Python's standard library.
# PDF objects follow the public PDF 1.7 format; no converter/library fixture is copied.
import hashlib
import pathlib
import struct
import sys
import zlib


def document(path, pages, encrypted=False):
    # pages: (media box, crop box, rotation). Coordinates in PDF points.
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'']
    font = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
    objects.append(font)
    image = b'\xff\x00\xff' * 16
    objects.append(b'<< /Type /XObject /Subtype /Image /Width 4 /Height 4 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 48 >>\nstream\n' + image + b'\nendstream')
    children = []
    for media, crop, rotation in pages:
        number = len(objects) + 1
        children.append(f'{number} 0 R')
        left, bottom, right, top = crop
        # Colour markers identify orientation, cropping, opacity and channel order.
        stream = (f'1 0 0 rg {left+10} {top-40} 30 30 re f\n'
                  f'0 0 1 rg {right-40} {bottom+10} 30 30 re f\n'
                  f'0 1 0 rg {left+10} {bottom+10} 30 30 re f\n'
                  # Interior markers remain visible at the viewer's 1.5x zoom.
                  f'1 0 0 rg {left+60} {top-130} 50 50 re f\n'
                  f'0 0 1 rg {left+130} {bottom+80} 50 50 re f\n'
                  f'0 1 0 rg {left+60} {bottom+80} 50 50 re f\n'
                  f'0 0 0 rg BT /F1 18 Tf {left+50} {top-65} Td (PDF MANUAL 123) Tj ET\n'
                  f'q 40 0 0 40 {left+60} {bottom+60} cm /Im1 Do Q\n').encode()
        objects.append((f'<< /Type /Page /Parent 2 0 R /MediaBox {media} /CropBox {crop} /Rotate {rotation} '
                        f'/Resources << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R >> >> /Contents {number+1} 0 R >>').encode())
        objects.append(b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'endstream')
    objects[1] = ('<< /Type /Pages /Kids [' + ' '.join(children) + f'] /Count {len(pages)} >>').encode()
    trailer = b''
    if encrypted:
        # Standard Security Handler revision 2 (40-bit RC4), nonempty user password.
        padding = bytes.fromhex('28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a')
        def padded(password):
            return (password + padding)[:32]
        def rc4(key, value):
            state = list(range(256)); j = 0
            for i in range(256):
                j = (j + state[i] + key[i % len(key)]) % 256
                state[i], state[j] = state[j], state[i]
            i = j = 0; result = bytearray()
            for byte in value:
                i = (i + 1) % 256; j = (j + state[i]) % 256
                state[i], state[j] = state[j], state[i]
                result.append(byte ^ state[(state[i] + state[j]) % 256])
            return bytes(result)
        owner = rc4(hashlib.md5(padded(b'owner')).digest()[:5], padded(b'required'))
        identity = hashlib.md5(b'ES-DE-Plus password fixture').digest()
        key = hashlib.md5(padded(b'required') + owner + struct.pack('<i', -4) + identity).digest()[:5]
        user = rc4(key, padding)
        for i, value in enumerate(objects):
            if b'stream\n' in value:
                prefix, data = value.split(b'stream\n', 1)
                stream, suffix = data.rsplit(b'\nendstream', 1) if b'\nendstream' in data else data.rsplit(b'endstream', 1)
                objkey = hashlib.md5(key + struct.pack('<I', i+1)[:3] + b'\0\0').digest()[:10]
                objects[i] = prefix + b'stream\n' + rc4(objkey, stream) + b'\nendstream' + suffix
        objects.append(f'<< /Filter /Standard /V 1 /R 2 /O <{owner.hex()}> /U <{user.hex()}> /P -4 >>'.encode())
        trailer = f' /Encrypt {len(objects)} 0 R /ID [<{identity.hex()}> <{identity.hex()}>]'.encode()
    output = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f'{index} 0 obj\n'.encode() + value + b'\nendobj\n')
    start = len(output)
    output.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R'.encode() + trailer +
                  f' >>\nstartxref\n{start}\n%%EOF\n'.encode())
    path.write_bytes(output)


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    normal = ('[0 0 240 320]', '[0 0 240 320]', 0)
    pages = [normal] + [('[0 0 400 500]', '[80 90 320 410]', rotation) for rotation in [0, 90, 180, 270]]
    # Parse boxes into coordinates above while retaining PDF array syntax.
    class Box(list):
        def __str__(self): return '[' + ' '.join(map(str, self)) + ']'
    def converted(pages):
        return [(Box(map(int, media.strip('[]').split())), Box(map(int, crop.strip('[]').split())), rotation)
                for media, crop, rotation in pages]
    document(directory / 'Manual spaces 🚀.pdf', converted(pages))
    document(directory / 'stress.pdf', converted([normal] * 60))
    document(directory / 'zero.pdf', [])
    document(directory / 'password.pdf', converted([normal]), encrypted=True)
    (directory / 'malformed.pdf').write_bytes(b'%PDF-1.4\ninvalid\n')
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress((b'\0' + b'\x00\xff\xff' * 16) * 16)) + chunk(b'IEND', b'')
    (directory / 'cover.png').write_bytes(png)
    print('PASS: generated 5-page colour/crop/rotation/text/image manual, 60-page stress, zero-page, password and malformed fixtures')


if __name__ == '__main__':
    generate(pathlib.Path(sys.argv[1]))
