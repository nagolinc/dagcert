from nagini_contracts.contracts import ContractOnly, Ensures, Result

from app import QueueTakeRequest, QueueTakeResponse


@ContractOnly
def get_job(request: QueueTakeRequest) -> QueueTakeResponse:
    Ensures(Result() is not None)
