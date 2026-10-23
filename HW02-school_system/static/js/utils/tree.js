/**
 * Pure tree utilities for menu manipulation. No DOM, no I/O — easy to test.
 */

/**
 * Normalise a query for case-insensitive comparison.
 */
export function normalise(value) {
  return (value == null ? "" : String(value)).toLowerCase().trim();
}

/**
 * Build a lookup map from id -> node for O(1) child lookup.
 */
export function indexById(items) {
  const map = new Map();
  for (const it of items || []) map.set(it.id, it);
  return map;
}

/**
 * Recursively find every node whose label (or any descendant's label)
 * matches the query. Returns a Set of node ids.
 */
export function collectMatchingIds(items, query) {
  const q = normalise(query);
  const matched = new Set();
  if (!q) return matched;

  const byParent = new Map();
  for (const it of items || []) {
    if (it.parent_id != null) {
      const list = byParent.get(it.parent_id) || [];
      list.push(it);
      byParent.set(it.parent_id, list);
    }
  }

  function labelHit(node) {
    return normalise(node.label).includes(q) || normalise(node.route || "").includes(q);
  }

  function collectSubtree(rootId) {
    matched.add(rootId);
    for (const child of byParent.get(rootId) || []) {
      collectSubtree(child.id);
    }
  }

  for (const node of items || []) {
    if (labelHit(node)) collectSubtree(node.id);
  }
  return matched;
}

/**
 * Build a nested tree (in-place) from flat items, using `children` arrays.
 * Returns the root array. Orphan nodes (parent missing) become roots.
 */
export function buildTree(items) {
  const byId = new Map();
  for (const it of items || []) {
    byId.set(it.id, { ...it, children: [] });
  }
  const roots = [];
  for (const node of byId.values()) {
    const pid = node.parent_id;
    if (pid != null && byId.has(pid)) {
      byId.get(pid).children.push(node);
    } else {
      roots.push(node);
    }
  }
  sortTree(roots);
  return roots;
}

function sortTree(nodes) {
  nodes.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.id - b.id);
  for (const n of nodes) sortTree(n.children);
}

/**
 * Given a tree and a query, prune branches that don't contain a match.
 * Returns a new tree (deep-cloned for safety).
 */
export function filterTree(tree, query) {
  const q = normalise(query);
  if (!q) return cloneTree(tree);

  function walk(node) {
    const selfHit = normalise(node.label).includes(q) || normalise(node.route || "").includes(q);
    const kids = (node.children || []).map(walk).filter(Boolean);
    if (selfHit || kids.length) {
      return { ...node, children: kids };
    }
    return null;
  }
  return tree.map(walk).filter(Boolean);
}

function cloneTree(tree) {
  return tree.map((n) => ({ ...n, children: cloneTree(n.children || []) }));
}

/**
 * Collect every leaf route from a tree.
 */
export function collectRoutes(tree) {
  const out = [];
  function walk(node) {
    if (node.route) out.push(node.route);
    for (const c of node.children || []) walk(c);
  }
  for (const n of tree) walk(n);
  return out;
}