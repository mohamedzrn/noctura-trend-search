from instagram.client import InstagramClient

c = InstagramClient()
c.login()
print("LOGIN OK — session saved to session.json")
