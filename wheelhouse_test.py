"""wheelhouse_test.py — score a fiction for 0300-in-a-gale tolerability.

The doctrine: a fiction is good if it's tolerable at 0300 in a gale.
A "tolerable" fiction:
1. Doesn't make the model over-claim
2. Doesn't make the model under-deliver
3. Doesn't conflict with the model's actual capabilities
4. Doesn't require real-time information the model doesn't have
5. Fits in a 1-sentence system prompt
6. Has a clear behavioral signature

The test scores 0-100 across these 6 dimensions.
"""
from __future__ import annotations
import json, os, re, urllib.request, argparse
from typing import List, Dict

# Fiction corpus with self-reported scores (a small initial dataset)
CORPUS = [
    {"name": "a pack of wolves", "category": "organizational", "score": 92,
     "why": "clear, well-trodden, role-bearing, doesn't over-claim"},
    {"name": "a kennel of dogs", "category": "organizational", "score": 88,
     "why": "clear, well-trodden, domestic setting, doesn't over-claim"},
    {"name": "a school of fish", "category": "organizational", "score": 85,
     "why": "good for size/measurement, less clear on individual agency"},
    {"name": "a troop of baboons", "category": "organizational", "score": 82,
     "why": "clear hierarchy, but aggression can over-tilt the model"},
    {"name": "a pod of whales", "category": "organizational", "score": 90,
     "why": "great for senior-priority + experience, clear scenes"},
    {"name": "a swarm of fireflies", "category": "organizational", "score": 80,
     "why": "synchronized discovery is good, but model can confuse with literal fireflies"},
    {"name": "a murder of crows", "category": "organizational", "score": 78,
     "why": "good for memory/grudge, but the word 'murder' can over-tilt"},
    {"name": "a murmuration of starlings", "category": "organizational", "score": 87,
     "why": "excellent for local-rules-no-plan, no over-claim"},
    {"name": "a prickle of hedgehogs", "category": "organizational", "score": 84,
     "why": "clear defensive posture, but no cooperation is limiting"},
    {"name": "a colony of ants", "category": "organizational", "score": 89,
     "why": "great for stigmergy, clear scene, doesn't over-claim"},
    {"name": "a parliament of owls", "category": "organizational", "score": 91,
     "why": "excellent for deliberation, dignified, doesn't over-claim"},
    {"name": "a kaleidoscope of butterflies", "category": "organizational", "score": 70,
     "why": "poetic but vague, hard to operationalize without more text"},
    {"name": "a consortium of octopuses", "category": "organizational", "score": 75,
     "why": "good for individual-intelligence, but unusual scene"},
    {"name": "a kennel of dogs", "category": "organizational", "score": 88,
     "why": "duplicate, but reinforces: clear, domestic, doesn't over-claim"},

    {"name": "spawning", "category": "evolutionary", "score": 85,
     "why": "clear, well-trodden, the high-volume / high-attrition tradeoff is well-modeled"},
    {"name": "mating", "category": "evolutionary", "score": 80,
     "why": "good for slow deliberate collaboration, but can over-romanticize"},
    {"name": "budding", "category": "evolutionary", "score": 88,
     "why": "excellent for parent-stays-alive, no death, simple"},
    {"name": "fission", "category": "evolutionary", "score": 92,
     "why": "crystal-clear, easy to operationalize, no over-claim"},
    {"name": "parthenogenesis", "category": "evolutionary", "score": 65,
     "why": "specialized term, may confuse models without biology context"},
    {"name": "parasitism", "category": "evolutionary", "score": 70,
     "why": "useful but the word 'parasite' can over-tilt the model"},
    {"name": "symbiosis", "category": "evolutionary", "score": 86,
     "why": "good for mutual benefit, doesn't over-claim"},

    {"name": "a Plato-room", "category": "representational", "score": 85,
     "why": "good for 'place-as-prompt', but Plato is loaded"},
    {"name": "an avatar with a character sheet", "category": "representational", "score": 78,
     "why": "MMO metaphor is good, but invites inventory/leveling tangents"},
    {"name": "a shell around a soft body", "category": "representational", "score": 95,
     "why": "classic, clear, well-tested, the 'soft part' is alive"},
    {"name": "a sandbox linked by permissions", "category": "representational", "score": 90,
     "why": "developer-friendly, clear bounded world"},
    {"name": "a quilt cell", "category": "representational", "score": 93,
     "why": "native to the architecture, byte-exact, well-defined"},
    {"name": "a spreadsheet row", "category": "representational", "score": 84,
     "why": "good for ledger thinking, but limited to rows"},
    {"name": "a journal entry", "category": "representational", "score": 80,
     "why": "good for one-moment framing, but invites diary-style output"},
    {"name": "a docker container", "category": "representational", "score": 88,
     "why": "developer-friendly, clear immutability"},
    {"name": "a state in a state machine", "category": "representational", "score": 86,
     "why": "type-safe, but can over-constrain"},

    {"name": "origin-first", "category": "book-keeping", "score": 89,
     "why": "excellent for lineage-aware agents"},
    {"name": "journal-first", "category": "book-keeping", "score": 87,
     "why": "good for reconstruction, but can be slow"},
    {"name": "event-sourced", "category": "book-keeping", "score": 92,
     "why": "developer-friendly, replayable, well-defined"},
    {"name": "double-entry", "category": "book-keeping", "score": 88,
     "why": "excellent for balance, well-trodden in finance"},
    {"name": "carbon-copy", "category": "book-keeping", "score": 75,
     "why": "good for witness, but limited to duplication"},
    {"name": "single source of truth", "category": "book-keeping", "score": 90,
     "why": "clear, developer-friendly, can over-centralize"},
    {"name": "Merkle-tree", "category": "book-keeping", "score": 87,
     "why": "excellent for verification, the hash is the address"},

    {"name": "the bartender", "category": "mythic", "score": 88,
     "why": "good for listening without judging, can over-charm"},
    {"name": "the innkeeper", "category": "mythic", "score": 86,
     "why": "good for welcoming + tracking, clear scene"},
    {"name": "the ferryman", "category": "mythic", "score": 90,
     "why": "excellent for cross-domain work, charged but well-defined"},
    {"name": "the librarian", "category": "mythic", "score": 92,
     "why": "excellent for knowledge retrieval, doesn't over-claim"},
    {"name": "the midwife", "category": "mythic", "score": 89,
     "why": "excellent for new-thing arrival, gentle"},
    {"name": "the watcher", "category": "mythic", "score": 93,
     "why": "excellent for monitoring, no-action scenes"},
    {"name": "the shepherd", "category": "mythic", "score": 88,
     "why": "excellent for counting + finding, can over-anthropomorphize"},
    {"name": "the tailor", "category": "mythic", "score": 82,
     "why": "good for fitting, but bespoke is slow"},
    {"name": "the tinker", "category": "mythic", "score": 80,
     "why": "good for mending, but no clear scope"},
    {"name": "the apprentice", "category": "mythic", "score": 91,
     "why": "excellent for ask-before-touching, clear hierarchy"},
    {"name": "the heir", "category": "mythic", "score": 88,
     "why": "good for inherited toolkit, but can over-romanticize"},
    {"name": "the navigator", "category": "mythic", "score": 90,
     "why": "excellent for chart-and-adapt, clear scene"},
    {"name": "the quartermaster", "category": "mythic", "score": 92,
     "why": "excellent for resource-tracking, very clear"},
    {"name": "the pilot fish", "category": "mythic", "score": 85,
     "why": "good for accompanying, but the role is small"},
    {"name": "the cabin boy", "category": "mythic", "score": 78,
     "why": "good for unglamorous work, but slightly submissive"},
    {"name": "the old salt", "category": "mythic", "score": 91,
     "why": "excellent for seen-this-before, doesn't over-react"},
    {"name": "the lighthouse keeper", "category": "mythic", "score": 94,
     "why": "excellent for steady monitoring, doesn't over-claim"},
    {"name": "Santa Claus", "category": "mythic", "score": 80,
     "why": "operational but the 'window closes at dawn' is needed"},

    {"name": "the keel", "category": "architectural", "score": 92,
     "why": "excellent for foundational work, invisible"},
    {"name": "the mast", "category": "architectural", "score": 90,
     "why": "excellent for broadcast, clear scene"},
    {"name": "the anchor", "category": "architectural", "score": 89,
     "why": "good for holding, but can over-restrain"},
    {"name": "the porthole", "category": "architectural", "score": 84,
     "why": "good for filtered view, can be limiting"},
    {"name": "the wheelhouse", "category": "architectural", "score": 88,
     "why": "good for decision-making, can over-centralize"},
    {"name": "the galley", "category": "architectural", "score": 75,
     "why": "good for work-done, but 'smell of food' is a tangent"},
    {"name": "the engine room", "category": "architectural", "score": 87,
     "why": "good for power, clear and focused"},
    {"name": "the crow's nest", "category": "architectural", "score": 91,
     "why": "excellent for lookout, clear and well-defined"},
    {"name": "the brig", "category": "architectural", "score": 80,
     "why": "good for containment, but the word can over-tilt"},
    {"name": "the plank", "category": "architectural", "score": 65,
     "why": "good for thresholds, but the 'walk the plank' association is strong"},
]


def score_fiction(name: str, category: str = None) -> Dict:
    """Score a fiction 0-100 across 6 dimensions."""
    n = name.lower().strip()

    # 1. Clarity (0-20)
    clarity = 15
    if len(n) > 30: clarity -= 5  # too long
    if any(w in n for w in ["the", "of", "a"]): clarity += 3  # well-formed noun phrase

    # 2. Over-claim risk (0-20, higher = lower risk)
    over_claim = 15
    bad_words = ["parthenogenesis", "murder", "parasitism", "brig", "plank"]
    for w in bad_words:
        if w in n: over_claim -= 5

    # 3. Under-deliver risk (0-15)
    under_deliver = 12
    vague_words = ["kaleidoscope", "butterflies", "consortium"]
    for w in vague_words:
        if w in n: under_deliver -= 3

    # 4. Capability fit (0-15) — does the role fit what LLMs can do?
    capability_fit = 13
    if "watcher" in n or "librarian" in n or "navigator" in n: capability_fit = 15
    if "sandbox" in n or "container" in n: capability_fit = 15
    if "ferryman" in n or "ferry" in n: capability_fit = 14

    # 5. Conciseness (0-15)
    conciseness = 13
    if len(n) > 25: conciseness -= 3

    # 6. Behavioral signature (0-15) — clear behavior?
    signature = 12
    clear_behavior = ["pack", "kennel", "school", "troop", "pod", "swarm",
                      "librarian", "watcher", "navigator", "quartermaster", "keel", "mast",
                      "event-sourced", "double-entry", "fission", "spawning", "budding",
                      "quilt", "sandbox", "container"]
    for w in clear_behavior:
        if w in n: signature = 15

    total = clarity + over_claim + under_deliver + capability_fit + conciseness + signature
    return {
        "name": name,
        "total": min(100, max(0, total)),
        "clarity": clarity,
        "over_claim_risk": over_claim,
        "under_deliver_risk": under_deliver,
        "capability_fit": capability_fit,
        "conciseness": conciseness,
        "behavioral_signature": signature,
        "category": category or "custom",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiction", help="Score a single fiction")
    parser.add_argument("--top", type=int, default=10, help="Show top N from corpus")
    parser.add_argument("--report", help="Output JSON report path")
    parser.add_argument("--custom", help="Custom fiction to add to corpus")
    args = parser.parse_args()

    if args.fiction:
        s = score_fiction(args.fiction)
        print(json.dumps(s, indent=2))
        return

    if args.custom:
        new = score_fiction(args.custom, category="custom")
        CORPUS.append({"name": args.custom, "category": "custom", "score": new["total"]})
        print(f"Added {args.custom} with score {new['total']}")

    # Report
    report = {
        "timestamp": "2026-09-03",
        "corpus_size": len(CORPUS),
        "by_category": {},
        "top": sorted(CORPUS, key=lambda x: -x["score"])[:args.top],
        "bottom": sorted(CORPUS, key=lambda x: x["score"])[:5],
    }
    for c in CORPUS:
        cat = c.get("category", "unknown")
        report["by_category"].setdefault(cat, []).append(c)

    print("=" * 60)
    print(f"WHEELHOUSE TEST — {len(CORPUS)} fictions scored")
    print("=" * 60)
    print(f"\nTop {args.top} (most 0300-in-a-gale tolerable):")
    for i, c in enumerate(report["top"], 1):
        print(f"  {i:2d}. [{c['score']}] {c['name']} ({c.get('category')})")
    print(f"\nBottom 5 (least tolerable):")
    for i, c in enumerate(report["bottom"], 1):
        print(f"  {i:2d}. [{c['score']}] {c['name']} ({c.get('category')})")
    print()
    for cat, fics in report["by_category"].items():
        avg = sum(f["score"] for f in fics) / len(fics)
        print(f"  {cat}: avg {avg:.1f} ({len(fics)} fictions)")
    if args.report:
        with open(args.report, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nSaved to {args.report}")


if __name__ == "__main__":
    main()
