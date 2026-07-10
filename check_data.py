import json, urllib.request
r = urllib.request.urlopen('http://localhost:5000/api/data')
d = json.loads(r.read())
g = d['grouped'][0]
print(f"=== User: {g['user']} | Device: {g['device']} ===")
print(f"totalPunnets: {g['totalPunnets']}")
print(f"totalWeight: {g['totalWeight']}")
print(f"totalSessions: {g['totalSessions']}")
print()
print("--- Production Entries (hourly) ---")
for p in g['productionEntries'][:3]:
    print(f"  {p['timeRange']} | {p['articleName']} | {p['punnets']} punnets | {p['netWeight']}kg | avg {p['avgWeight']}kg")
print(f"  ... ({len(g['productionEntries'])} total)")
print()
print("--- Session Entries ---")
for s in g['sessionEntries'][:3]:
    print(f"  {s['loginTime']} -> {s['logoutTime']} | {s['activity']} | {s['workingTime']} | {s['line']}")
print(f"  ... ({len(g['sessionEntries'])} total)")
