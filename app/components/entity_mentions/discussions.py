import datetime as dt
from types import SimpleNamespace

from app.setup import gh

DISCUSSION_QUERY = """
query getDiscussion($number: Int!, $org: String!, $repo: String!) {
  repository(owner: $org, name: $repo) {
    discussion(number: $number) {
      title
      number
      user: author { login }
      created_at: createdAt
      html_url: url
      answered: isAnswered
    }
  }
}
"""


def get_discussion(org: str, name: str, number: int) -> SimpleNamespace:
    resp = gh.graphql.request(
        DISCUSSION_QUERY, variables={"number": number, "org": org, "repo": name}
    )
    data = resp["repository"]["discussion"]
    return SimpleNamespace(
        user=SimpleNamespace(login=data.pop("user")["login"]),
        created_at=dt.datetime.fromisoformat(data.pop("created_at")),
        **data,
    )
