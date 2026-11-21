package bench.fw;

import java.sql.Connection;
import java.sql.SQLException;
import org.hibernate.engine.jdbc.connections.spi.ConnectionProvider;

/** Hibernate connection provider without pooling: every session opens a real Connector/J connection (as in T1). */
public class NonPooled implements ConnectionProvider {
    public static volatile String tls = "off";
    public static volatile boolean sock = false;

    @Override public Connection getConnection() throws SQLException { return bench.Runner.connect(tls, sock); }
    @Override public void closeConnection(Connection c) throws SQLException { c.close(); }
    @Override public boolean supportsAggressiveRelease() { return false; }
    @Override public boolean isUnwrappableAs(Class<?> t) { return false; }
    @Override public <T> T unwrap(Class<T> t) { throw new UnsupportedOperationException(); }
}
