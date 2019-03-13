@0xdc4b924ea7e6c290;

struct Schema {
    type @0 :Type;
    size @1 :UInt32;
    email @2 :Text;
    txId @3 :Text; # transaction id of the reservation
    creationTimestamp @4 :Int32;
    webGateway @5 :Text="web_gateway"; # web gateway to use for reverse proxy for s3 service

    enum Type {
        vm @0;
        s3 @1;
    }
}
