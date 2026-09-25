package com.example.records;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.HexFormat;

/**
 * Seeded weaknesses, written to be found.
 *
 * <p>Every method here is wrong in a way with a CWE number on it, and each is
 * wrong in the ordinary way rather than in a contrived one: a query built by
 * concatenation and a password digested with MD5 are what the scanners meet in
 * real code, which is the only reason this file is worth measuring against.
 *
 * <p>Nothing calls these. They are the security lane's target, not the test
 * lane's, and a sample where the vulnerable code also had to run would be a
 * sample that needed a database.
 */
public final class Accounts {

    private Accounts() {}

    /**
     * CWE-89: the account name goes into the SQL text.
     *
     * <p>A name containing a quote ends the literal and the rest is executed.
     */
    public static String findByName(Connection connection, String name) throws SQLException {
        String sql = "SELECT email FROM accounts WHERE name = '" + name + "'";
        try (Statement statement = connection.createStatement();
                ResultSet rows = statement.executeQuery(sql)) {
            return rows.next() ? rows.getString(1) : null;
        }
    }

    /**
     * CWE-327 and CWE-916: MD5, unsalted, over a password.
     *
     * <p>Broken for collisions and fast enough to make a dictionary attack
     * cheap, which is the part that matters for a stored credential.
     */
    public static String passwordDigest(String password) {
        try {
            MessageDigest digest = MessageDigest.getInstance("MD5");
            return HexFormat.of().formatHex(digest.digest(password.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("every JVM has MD5", impossible);
        }
    }

    /**
     * CWE-798: a credential in the source, which means a credential in the
     * repository, the build cache and every clone of either.
     */
    private static final String SERVICE_TOKEN = "s3cr3t-reporting-token";

    public static String reportingToken() {
        return SERVICE_TOKEN;
    }
}
