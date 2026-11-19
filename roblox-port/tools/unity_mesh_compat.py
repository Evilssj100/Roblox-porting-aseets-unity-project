"""Mesh access that also works for Unity 3.2-era assets (the SHSO archive's character bundles), whose
meshes keep m_Vertices / m_Normals / m_UV / m_Skin arrays instead of the m_VertexData streams that
UnityPy's MeshHandler expects.

    h = mesh_handler(mesh)   # same attributes the tools use: m_Vertices, m_Normals, m_UV0,
                             # m_BoneWeights, m_BoneIndices, m_IndexBuffer, m_Use16BitIndices
"""
import numpy as np
from UnityPy.helpers.MeshHelper import MeshHandler


class _OldMesh:
    def __init__(self, tt):
        def vec(key, dims):
            arr = tt.get(key) or []
            names = "xyzw"[:dims]
            return [float(v[c]) for v in arr for c in names]
        self.m_Vertices = vec("m_Vertices", 3)
        self.m_Normals = vec("m_Normals", 3)
        self.m_UV0 = vec("m_UV", 2)
        skin = tt.get("m_Skin") or []
        w, j = [], []
        for s in skin:
            w += [float(s.get(f"weight[{i}]", 0)) for i in range(4)]
            j += [int(s.get(f"boneIndex[{i}]", 0)) for i in range(4)]
        self.m_BoneWeights, self.m_BoneIndices = w, j
        ib = tt.get("m_IndexBuffer") or b""
        self.m_IndexBuffer = bytes(ib) if not isinstance(ib, (bytes, bytearray)) else ib
        self.m_Use16BitIndices = int(tt.get("m_Use16BitIndices", 1))


def mesh_handler(mesh):
    tt = mesh.object_reader.read_typetree() if hasattr(mesh, "object_reader") else None
    if tt is not None and "m_VertexData" not in tt and tt.get("m_Vertices"):
        return _OldMesh(tt)
    h = MeshHandler(mesh)
    h.process()
    return h


def pick_skinned_renderer(renderers):
    """the LOD0 skinned mesh when the bundle has LODs, otherwise the one with the most vertices"""
    best, best_n = None, -1
    for s in renderers:
        if not (s.m_Mesh and s.m_Mesh.m_PathID):
            continue
        m = s.m_Mesh.read()
        if m.m_Name.lower().endswith("lod0"):
            return s
        n = len(m.object_reader.read_typetree().get("m_Vertices") or []) or (m.m_VertexData.m_VertexCount if getattr(m, "m_VertexData", None) else 0)
        if n > best_n:
            best, best_n = s, n
    return best
