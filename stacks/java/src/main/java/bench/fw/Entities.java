package bench.fw;

import jakarta.persistence.*;

/** Hand-written JPA entities for the narrow tables (the 100-column ones are generated). */
public final class Entities {
    private Entities() {}

    @Entity(name = "TInt") @Table(name = "t_int")
    public static class TInt {
        @Id public Integer id;
        @Column(name = "v") public Integer v;
    }

    @Entity(name = "TBlob") @Table(name = "t_blob")
    public static class TBlob {
        @Id public Integer id;
        @Column(name = "size_class") public String sizeClass;
        @Column(name = "doc") public String doc;
        @Column(name = "doc_bin") public byte[] docBin;
    }

    @Entity(name = "TBulk") @Table(name = "t_bulk")
    public static class TBulk {
        @Id public Integer id;
        @Column(name = "a") public Integer a;
        @Column(name = "b") public String b;
        @Column(name = "c") public Double c;
        public TBulk() {}
        public TBulk(int id, int a, String b, double c) { this.id = id; this.a = a; this.b = b; this.c = c; }
    }
}
