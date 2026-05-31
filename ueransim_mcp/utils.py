import random
import string


def generate_random_suffix(length: int = 4) -> str:
    """Return a random lowercase-alphanumeric string of the given length."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
