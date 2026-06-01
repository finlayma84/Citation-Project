from music_picker import create_app
from music_picker.services import get_repertoire_results, normalize_search_text

def show(query):
    rows, total = get_repertoire_results(search_q=query, season="", slot="", limit=10)
    print()
    print(f"Query: {query!r}")
    print(f"Total: {total}")
    for r in rows[:10]:
        print(f"  - {r['title']} | {r['composer']}")

def main():
    app = create_app()
    with app.app_context():
        print("Normalization examples:")
        for s in [
            "Angels' Carol",
            "angels carol",
            "Come, O Long-expected Jesus",
            "Noël",
        ]:
            print(f"  {s!r} -> {normalize_search_text(s)!r}")

        show("angels carol")
        show("angel's carol")
        show("come o long expected jesus")
        show("sheep may safely graze")

if __name__ == "__main__":
    main()
