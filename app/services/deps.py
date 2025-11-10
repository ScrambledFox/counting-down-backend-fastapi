from fastapi import Depends

from app.db.deps import get_together_list_repo
from app.repositories.together_list import TogetherListRepository
from app.services.together_list import TogetherListService


async def get_together_list_service(
    repo: TogetherListRepository = Depends(get_together_list_repo),
) -> TogetherListService:
    return TogetherListService(repo)
