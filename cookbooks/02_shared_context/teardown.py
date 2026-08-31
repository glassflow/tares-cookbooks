"""Delete the project (and everything it created, plus its events) and the credential.
The GitHub repos stay; delete them yourself if they were throwaways."""
import tares_client as tc


def main() -> None:
    tc.check_tares()
    uc = tc.find_project()
    if uc:
        tc.delete_project(uc["id"], purge_events=True)
        print(f"deleted project {uc['id']}")
    else:
        print("no project to delete")
    tc.delete_credential()
    print(f"deleted credential {tc.CREDENTIAL} (if it existed)")


if __name__ == "__main__":
    main()
