"""
Direct query runner — bypasses HTTP/auth to call answer_query() directly
and capture all debug prints alongside the answers.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from backend.rag.llm_chain import answer_query

QUERIES = [
    # --- SOLO (5) ---
    "What projects is Praney working on alone?",
    "What projects is Pratyush working on alone?",
    "What projects is Anoushka working on alone?",
    "What projects is Tarun working on alone?",
    "What projects is Manoj working on alone?",

    # --- INTERSECTION (5) ---
    "What projects do Anoushka and Pratyush work on together?",
    "What projects do Praney and Pratyush work on together?",
    "What projects do Anoushka and Praney work on together?",
    "What projects do Anoushka and Manoj work on together?",
    "What projects do Tarun and Praney work on together?",

    # --- NEGATION (3) ---
    "What projects is Anoushka NOT working on?",
    "What projects is Pratyush NOT working on?",
    "What projects is Praney NOT working on?",

    # --- PERSON GENERAL (2) ---
    "What is Anoushka working on?",
    "What is Pratyush working on?",

    # --- AGGREGATE / GROUPING (6) ---
    "List all projects",
    "How many projects are there in total?",
    "Which category has the most projects?",
    "Who has the most projects?",
    "Which projects have more than 2 people involved?",
    "Which projects have only one person involved?",

    # --- STATUS (5) ---
    "How many projects are Not yet started?",
    "List all projects that are Completed",
    "How many projects are In Progress?",
    "List all projects that are Initiated",
    "What projects are Cancelled?",

    # --- CATEGORY LOOKUP (3) ---
    "Who is working on Hackathon projects?",
    "Who is working on CUAS projects?",
    "Who is working on Hardware Implementation projects?",

    # --- TEMPORAL (2) ---
    "Which projects have a date of 27-Feb?",
    "Which projects have deadlines mentioned?",

    # --- EDGE CASES / HALLUCINATION TRAPS (6) ---
    "What projects is John working on?",
    "What projects do Anoushka and John work on together?",
    "What is the budget for Hackathon projects?",
    "Which projects are overdue?",
    "What projects is Sarah working on?",
    "What do Anoushka and Sarah work on together?",
]

for i, q in enumerate(QUERIES, 1):
    print(f"\n{'='*70}")
    print(f"QUERY {i}: {q}")
    print('='*70)
    result = answer_query(q)
    print(f"\n--- INTENT: {result['query_intent']} ---")
    print(f"\nANSWER:\n{result['answer']}")
    print(f"\nSOURCES ({len(result['sources'])}):")
    for s in result['sources']:
        print(f"  • {s['filename']} [{s['relevance']}]")
