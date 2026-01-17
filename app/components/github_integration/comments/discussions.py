from base64 import urlsafe_b64encode
from typing import TYPE_CHECKING

import msgpack
from githubkit.exception import GraphQLFailed

from app.components.github_integration.models import Comment, Discussion

if TYPE_CHECKING:
    from app.components.github_integration.models import EntityGist
    from toolbox.misc import GH

DISCUSSION_COMMENT_QUERY = """
query getDiscussionComment($id: ID!) {
  node(id: $id) {
    ... on DiscussionComment {
      body
      discussion {
        body
        title
        number
        user: author {
          login
          html_url: url
          avatar_url: avatarUrl
        }
        created_at: createdAt
        html_url: url
        state_reason: stateReason
        closed
        answer {
          user: author {
            login
            html_url: url
            avatar_url: avatarUrl
          }
        }
      }
      author {
        login
        url
        icon_url: avatarUrl
      }
      created_at: createdAt
      html_url: url
    }
  }
}
"""


async def get_discussion_comment(
    gh: GH, entity_gist: EntityGist, comment_id: int
) -> Comment | None:
    packed = msgpack.packb([0, 0, comment_id])
    node_id = "DC_" + urlsafe_b64encode(packed).decode()
    try:
        resp = await gh.graphql.arequest(
            DISCUSSION_COMMENT_QUERY, variables={"id": node_id}
        )
    except GraphQLFailed:
        return None
    discussion = resp["node"].pop("discussion")
    discussion["answered_by"] = (answer := discussion.pop("answer")) and answer["user"]
    return Comment(
        **resp["node"],
        entity_gist=entity_gist,
        entity=Discussion(**discussion),
    )
