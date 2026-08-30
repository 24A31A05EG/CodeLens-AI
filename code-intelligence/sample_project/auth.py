def login(username, password):
    if username == "admin" and password == "password":
        return True

    return False


def logout(username):
    print(f"{username} logged out")