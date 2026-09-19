"""Export only native object attributes; avoid serializing the entire graph to disk."""


def object_nodes(graph):
    import spark_dsg

    nodes = []
    for node in graph.nodes:
        attrs = node.attributes
        if not isinstance(attrs, spark_dsg.ObjectNodeAttributes):
            continue
        nodes.append(
            {
                "id": int(node.id.value),
                "attributes": {
                    "type": "ObjectNodeAttributes",
                    "semantic_label": int(attrs.semantic_label),
                    "mesh_connections": [int(i) for i in attrs.mesh_connections],
                    "is_active": bool(attrs.is_active),
                    "last_update_time_ns": int(attrs.last_update_time_ns),
                },
            }
        )
    return nodes


def agent_poses(graph):
    import numpy as np
    import spark_dsg

    poses = []
    for node in graph.nodes:
        attrs = node.attributes
        if not isinstance(attrs, spark_dsg.AgentNodeAttributes):
            continue
        stamp = attrs.timestamp
        seconds = stamp.total_seconds() if hasattr(stamp, "total_seconds") else float(stamp) / 1e9
        q = attrs.world_R_body
        poses.append([seconds, *attrs.position, q.w, q.x, q.y, q.z])
    return np.asarray(poses, dtype="f8").reshape(-1, 8)
