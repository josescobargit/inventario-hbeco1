import re


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError(
            "El usuario debe tener entre 3 y 50 caracteres y usar letras, "
            "números, punto, guion o guion bajo."
        )
    return username
