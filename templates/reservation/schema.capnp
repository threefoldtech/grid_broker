@0x9270e6b3bb8a042e;

struct Schema {
    type @0 :Type;
    size @1 :UInt32;
    email @2 :Text;
    txId @3 :Text; # transaction id of the reservation
    creationTimestamp @4 :Int32;
    webGateway @5 :Text="web_gateway"; # web gateway to use for reverse proxy for s3 service
    location @6 :Text;
    diskType @7 :DiskType;
    namespaceMode @8 :NamespaceMode;
    password @9 :Text;
    domain @10 :Text;
    backendUrls @11 :List(Text);

    # the list of service id created by this reservation
    # this is automaticallty filled
    createdServices @12 :List(CreatedService);

    enum Type {
        vm @0;
        s3 @1;
        namespace @2;
    }

    enum DiskType {
        ssd @0;
        hdd @1;
    }

    enum NamespaceMode {
        direct @0;
        user @1;
        seq @2;
    }

    struct CreatedService{
        robot @0 :Text;
        id @1 :Text;
    }
}
