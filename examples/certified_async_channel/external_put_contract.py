from nagini_contracts.contracts import ContractOnly, Ensures, Result

from app import QueuePutRequest, QueuePutResponse


@ContractOnly
def put_job(request: QueuePutRequest) -> QueuePutResponse:
    Ensures(Result() is not None)
