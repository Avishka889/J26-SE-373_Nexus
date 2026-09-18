package com.example.records;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Two more seeded weaknesses, of the kinds a report feature usually grows.
 *
 * <p>Same rule as {@link Accounts}: ordinary mistakes, not puzzles.
 */
public final class Reports {

    private Reports() {}

    private static final Path ARCHIVE = Path.of("/var/reports");

    /**
     * CWE-78: the caller's name is pasted into a shell command.
     *
     * <p>A name of {@code x; rm -rf /} is two commands, and the second one runs.
     */
    public static Process archive(String name) throws IOException {
        String command = "tar -czf /var/reports/" + name + ".tar.gz /var/reports/" + name;
        return Runtime.getRuntime().exec(new String[] {"sh", "-c", command});
    }

    /**
     * CWE-22: the caller's name is joined to a directory and read.
     *
     * <p>A name of {@code ../../etc/passwd} leaves the directory it was meant
     * to stay inside, because nothing here checks that it stayed.
     */
    public static String read(String name) throws IOException {
        File target = new File(ARCHIVE.toFile(), name);
        return Files.readString(target.toPath());
    }
}
