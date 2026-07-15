import json
import threading


class GraphExporter:
    def __init__(self):
        self.edges = []
        self.nodes = set()
        self._lock = threading.Lock()

    def add_edge(self, source, target):
        with self._lock:
            self.edges.append((source, target))
            self.nodes.add(source)
            self.nodes.add(target)

    def export_json(self, filepath):
        with self._lock:
            data = {
                "nodes": list(self.nodes),
                "edges": [{"source": s, "target": t} for s, t in self.edges],
            }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def export_dot(self, filepath):
        with self._lock:
            lines = ["digraph XueCrawl {", '  rankdir=LR;', '  node [shape=box, fontsize=8];']
            for s, t in self.edges:
                src = s.replace('"', '\\"')[:80]
                tgt = t.replace('"', '\\"')[:80]
                lines.append(f'  "{src}" -> "{tgt}";')
            lines.append("}")
        with open(filepath, "w") as f:
            f.write("\n".join(lines))

    def export_gexf(self, filepath):
        with self._lock:
            node_ids = {n: i for i, n in enumerate(self.nodes)}
            lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                     '<gexf xmlns="http://www.gexf.net/1.2" version="1.2">',
                     '  <graph defaultedgetype="directed">',
                     '    <nodes>']
            for node, nid in node_ids.items():
                label = node[:80].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f'      <node id="{nid}" label="{label}" />')
            lines.append('    </nodes>')
            lines.append('    <edges>')
            for i, (s, t) in enumerate(self.edges):
                lines.append(f'      <edge id="{i}" source="{node_ids[s]}" target="{node_ids[t]}" />')
            lines.append('    </edges>')
            lines.append('  </graph>')
            lines.append('</gexf>')
        with open(filepath, "w") as f:
            f.write("\n".join(lines))
