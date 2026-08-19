"""Delete the use case (and everything it created, plus its events) and the credential.
The GitHub repos stay; delete them yourself if they were throwaways."""
import tares_client as tc


def main() -> None:
    tc.check_tares()
    uc = tc.find_usecase()
    if uc:
        tc.delete_usecase(uc["id"], purge_events=True)
        print(f"deleted use case {uc['id']}")
    else:
        print("no use case to delete")
    tc.delete_credential()
    print(f"deleted credential {tc.CREDENTIAL} (if it existed)")


if __name__ == "__main__":
    main()
