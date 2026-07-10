import json, base64, time

token = open(".token").read().strip()
payload = token.split(".")[1]
padding = 4 - len(payload) % 4
if padding != 4:
    payload += "=" * padding
claims = json.loads(base64.urlsafe_b64decode(payload))
exp = claims.get("exp", 0)
remaining = (exp - time.time()) / 3600
user = claims.get("x-user-name", "?")
print(f"Token valid: {remaining:.1f}h remaining, user={user}")
