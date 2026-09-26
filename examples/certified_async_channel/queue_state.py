"""The one physical queue shared by the external put and get adapters."""

from queue import Queue

from app import PreparedJob


work_queue: Queue[PreparedJob] = Queue()
