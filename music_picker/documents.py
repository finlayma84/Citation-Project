def generate_document_template(season, year):
    from generate_doc import generate_template
    return generate_template(season, year)


def sync_document_for_season(season, year):
    from update_doc import update_doc_for_season
    return update_doc_for_season(season, year)


def try_sync_doc(season, year):
    try:
        return sync_document_for_season(season, year)
    except Exception as e:
        print(f"Doc sync failed: {e}")
        return False, str(e)
