"""The restored wireframe avatar has a valid, self-contained geometry."""
import json
import struct
from pathlib import Path


def test_shipped_wireframe_avatar_has_loadable_geometry():
    raw = (Path(__file__).parents[2] / 'frontend/public/models/avatar.glb').read_bytes()
    assert raw[:4] == b'glTF'
    assert struct.unpack_from('<I', raw, 8)[0] == len(raw)
    size = struct.unpack_from('<I', raw, 12)[0]
    gltf = json.loads(raw[20:20 + size])
    assert gltf['meshes']
    for mesh in gltf['meshes']:
        for primitive in mesh['primitives']:
            accessor = gltf['accessors'][primitive['attributes']['POSITION']]
            assert accessor['count'] > 0 and accessor['type'] == 'VEC3'
    assert all('uri' not in buffer for buffer in gltf['buffers'])
