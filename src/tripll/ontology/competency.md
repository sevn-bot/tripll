# Ontology competency questions

The graph must answer these ten questions. Each entry records the traversal
(or SQL hint) used to answer it against the three-layer schema.

```yaml
questions:
  - id: 1
    question: Which specs and requirements govern the file this wave is about to edit?
    traversal: "Wave -TARGETS-> Module <-OWNS- Spec -SPECIFIES-> Requirement"
    sql_hint: |
      SELECT req.natural_key FROM edges t
        JOIN nodes mod ON t.dst = mod.node_id
        JOIN edges o ON o.dst = mod.node_id AND o.predicate = 'OWNS'
        JOIN edges s ON s.src = o.src AND s.predicate = 'SPECIFIES'
        JOIN nodes req ON s.dst = req.node_id
       WHERE t.src = :wave_id AND t.predicate = 'TARGETS'

  - id: 2
    question: Which tests cover this symbol, and which of them currently fail?
    traversal: "Symbol <-COVERS- Test; join CIcheck -RUNS-> MakeTarget -VERIFIES-> Test"
    sql_hint: |
      SELECT t.node_id FROM edges c
        JOIN nodes sym ON c.dst = sym.node_id
        JOIN nodes t ON c.src = t.node_id
       WHERE sym.node_id = :symbol_id AND c.predicate = 'COVERS'

  - id: 3
    question: Which failing CI check maps to which changed symbol, and which requirement does that symbol implement?
    traversal: "Finding -ABOUT-> Symbol -IMPLEMENTS-> Requirement; Finding -RAISED_BY-> CIcheck"
    sql_hint: |
      WITH RECURSIVE reach(node_id, depth, path) AS (
          SELECT dst, 0, dst FROM edges
           WHERE src = :finding_id AND predicate = 'ABOUT' AND valid_to IS NULL
        UNION ALL
          SELECT e.dst, r.depth + 1, r.path || '>' || e.dst
            FROM edges e JOIN reach r ON e.src = r.node_id
           WHERE r.depth < 2
             AND e.predicate IN ('CALLS','IMPLEMENTS','COVERS','DECLARES')
             AND e.valid_to_sha IS NULL
      )
      SELECT n.kind, n.natural_key, r.path FROM reach r
        JOIN nodes n ON n.node_id = r.node_id
       WHERE n.kind IN ('Requirement','Spec','Test')

  - id: 4
    question: Is this review finding about code a later wave already rewrote?
    traversal: "Finding -ABOUT-> Symbol WHERE valid_to_sha IS NOT NULL"
    sql_hint: |
      SELECT sym.valid_to_sha FROM edges e
        JOIN nodes sym ON e.dst = sym.node_id
       WHERE e.src = :finding_id AND e.predicate = 'ABOUT'
         AND sym.valid_to_sha IS NOT NULL

  - id: 5
    question: What is the minimum set of files an agent must read to execute wave W?
    traversal: "Wave -TARGETS-> Module; 2-hop subgraph capped at owned paths"
    sql_hint: |
      WITH RECURSIVE reach(node_id, depth) AS (
          SELECT dst, 0 FROM edges WHERE src = :wave_id AND predicate = 'TARGETS'
        UNION ALL
          SELECT e.dst, r.depth + 1 FROM edges e JOIN reach r ON e.src = r.node_id
           WHERE r.depth < 2 AND e.predicate IN ('DECLARES','IMPORTS','SPECIFIES')
      )
      SELECT DISTINCT n.natural_key FROM reach r JOIN nodes n ON n.node_id = r.node_id
       WHERE n.kind = 'Module'

  - id: 6
    question: Which two waves would collide on the same file?
    traversal: "Wave -TARGETS-> Module <-TARGETS- Wave (same Module node)"
    sql_hint: |
      SELECT w2.node_id FROM edges t1
        JOIN edges t2 ON t1.dst = t2.dst AND t1.src != t2.src
        JOIN nodes w2 ON t2.src = w2.node_id
       WHERE t1.predicate = 'TARGETS' AND t2.predicate = 'TARGETS'

  - id: 7
    question: Which prompts/agents took part in attempts that failed for reason R?
    traversal: "Attempt -RAN_AGENT-> AgentDef; Attempt -USED_PROMPT-> PromptDef WHERE outcome=failed"
    sql_hint: |
      SELECT a.node_id, ag.natural_key, pr.natural_key FROM nodes att
        JOIN edges ra ON ra.src = att.node_id AND ra.predicate = 'RAN_AGENT'
        JOIN nodes ag ON ra.dst = ag.node_id
        JOIN edges up ON up.src = att.node_id AND up.predicate = 'USED_PROMPT'
        JOIN nodes pr ON up.dst = pr.node_id
       WHERE att.props LIKE '%\"outcome\":\"failed\"%'

  - id: 8
    question: Which agent/prompt version has the highest first-attempt pass rate for problem type P?
    traversal: "Attempt -RAN_AGENT-> AgentDef GROUP BY content_hash WHERE attempt_n=1"
    sql_hint: |
      SELECT ag.natural_key, COUNT(*) FROM nodes att
        JOIN edges ra ON ra.src = att.node_id AND ra.predicate = 'RAN_AGENT'
        JOIN nodes ag ON ra.dst = ag.node_id
       WHERE json_extract(att.props, '$.attempt_n') = 1
       GROUP BY ag.natural_key

  - id: 9
    question: Did change C to agent A move metric M, and by how much versus predicted?
    traversal: "Experiment -PREDICTED-> Metric; Experiment -REALIZED-> Metric"
    sql_hint: |
      SELECT pred.props, real.props FROM nodes exp
        JOIN edges ep ON ep.src = exp.node_id AND ep.predicate = 'PREDICTED'
        JOIN edges er ON er.src = exp.node_id AND er.predicate = 'REALIZED'
        JOIN nodes pred ON ep.dst = pred.node_id
        JOIN nodes real ON er.dst = real.node_id
       WHERE exp.node_id = :experiment_id

  - id: 10
    question: What is the provenance of this requirement — which PRD, which issue, which commit?
    traversal: "Requirement <-SPECIFIES- Spec; Symbol -IMPLEMENTS-> Requirement; Attempt -PRODUCED-> Commit"
    sql_hint: |
      SELECT spec.natural_key, sym.natural_key, cmt.natural_key
        FROM nodes req
        JOIN edges s ON s.dst = req.node_id AND s.predicate = 'SPECIFIES'
        JOIN nodes spec ON s.src = spec.node_id
        LEFT JOIN edges i ON i.dst = req.node_id AND i.predicate = 'IMPLEMENTS'
        LEFT JOIN nodes sym ON i.src = sym.node_id
        LEFT JOIN edges p ON p.predicate = 'PRODUCED'
        LEFT JOIN nodes cmt ON p.dst = cmt.node_id
       WHERE req.node_id = :requirement_id
```
