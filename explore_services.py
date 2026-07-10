"""Explore gRPC services to find APIs for individual weighing records and login/logout times."""
import grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc
from google.protobuf import descriptor_pb2 as dp2
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass

GRPC_SERVER = "192.168.30.8:37270"
token = open(".token").read().strip()
meta = [("authorization", f"Bearer {token}")]

channel = grpc.insecure_channel(GRPC_SERVER)
stub = reflection_pb2_grpc.ServerReflectionStub(channel)

# List all services
req = reflection_pb2.ServerReflectionRequest(list_services="")
for r in stub.ServerReflectionInfo(iter([req]), metadata=meta):
    if r.HasField("list_services_response"):
        services = [s.name for s in r.list_services_response.service]
        print(f"Total services: {len(services)}")
        for s in sorted(services):
            print(f"  {s}")

# Look for services related to weighing, production, login, session
keywords = ["weighing", "login", "session", "production", "record", "punnet", "registration"]
print("\n=== Services matching keywords ===")
for s in sorted(services):
    sl = s.lower()
    for kw in keywords:
        if kw in sl:
            print(f"  [{kw}] {s}")
            break

# For each interesting service, get its methods
print("\n=== Method details for interesting services ===")
pool = DescriptorPool()
added = set()

def add_file(fn):
    if fn in added:
        return
    req2 = reflection_pb2.ServerReflectionRequest(file_by_filename=fn)
    for r2 in stub.ServerReflectionInfo(iter([req2]), metadata=meta):
        if r2.HasField("file_descriptor_response"):
            for b in r2.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(b)
                if fd.name not in added:
                    for dep in fd.dependency:
                        add_file(dep)
                    try:
                        pool.Add(fd)
                    except:
                        pass
                    added.add(fd.name)

def add_sym(symbol):
    req2 = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
    for r2 in stub.ServerReflectionInfo(iter([req2]), metadata=meta):
        if r2.HasField("file_descriptor_response"):
            for b in r2.file_descriptor_response.file_descriptor_proto:
                fd = dp2.FileDescriptorProto()
                fd.ParseFromString(b)
                if fd.name not in added:
                    for dep in fd.dependency:
                        add_file(dep)
                    try:
                        pool.Add(fd)
                    except:
                        pass
                    added.add(fd.name)

interesting = [s for s in services if any(kw in s.lower() for kw in 
    ["weighing", "login", "session", "production", "record", "report", "statistic"])]

for svc_name in interesting:
    add_sym(svc_name)
    try:
        sd = pool.FindServiceByName(svc_name)
        print(f"\n{svc_name}:")
        for m in sd.methods:
            print(f"  {m.name}({m.input_type.name}) -> {m.output_type.name}")
    except Exception as e:
        print(f"\n{svc_name}: ERROR {e}")

channel.close()
