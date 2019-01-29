@0xc5744bb1f5e43a0a;

struct Schema {
    type @0 :Type;
    size @1 :Integer
    email @2 :Text;
    txId @3 :Text; # transaction id of the reservation
    creationTimestamp @4 :Integer;

    enum Type {
        vm @0;
        s3 @1;
    }
}