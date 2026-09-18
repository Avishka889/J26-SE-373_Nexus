# java-sample

The Java lane's target: a small Maven project with a Maven Wrapper, JUnit 5,
JaCoCo and PIT, and a handful of seeded weaknesses for the security lane.

Everything here is hand written. Nothing is copied from a benchmark or a real
project, which keeps the licence question from arising at all inside this
repository, and the benchmarks the study actually scores against
(OWASP Benchmark, CWE-Bench-Java) are checked out at evaluation time rather
than vendored.

## Two deviations from the plan, and why

**It is `java-sample`, not `spring-sample`.** The plan named a Spring sample.
Spring Boot would add around forty megabytes to a first build that already
downloads Maven itself, and would buy realism the lanes do not need: the
scanners read source and bytecode, so a `@RestController` around a SQL string
is detected exactly as a plain class around one is, and the benchmarks supply
real-world Java for the study. The name says what it is.

**No jar is committed.** `mvnw` is the wrapper's own script and it downloads
`maven-wrapper.jar` and the Maven distribution on its first run, into the
sandbox's home rather than the developer's. That is what the script exists for,
and it keeps a binary out of a research repository.

## Deliberately not all green

`Totals.freeDelivery` has no test, one case is `@Disabled`, and the seeded
weaknesses are never called. So a report over this sample has a coverage number
below a hundred, mutants that nothing kills, and a case the framework declined
to run: the three things a fixture where everything passed could never show.

## The seeded weaknesses

| Class | Method | Weakness |
|---|---|---|
| `Accounts` | `findByName` | CWE-89, SQL built by concatenation |
| `Accounts` | `passwordDigest` | CWE-327 and CWE-916, unsalted MD5 over a password |
| `Accounts` | `reportingToken` | CWE-798, a credential in the source |
| `Reports` | `archive` | CWE-78, a shell command built from an argument |
| `Reports` | `read` | CWE-22, a path joined from an argument and never checked |

The token in `Accounts` is a made up string in a fixture. It authenticates
nothing, here or anywhere.

## Running it by hand

```
./mvnw -q test                 # JUnit 5 plus the JaCoCo agent and report
./mvnw -q test-compile org.pitest:pitest-maven:mutationCoverage \
  -DtargetClasses=com.example.records.Totals
```

The first run is slow: it fetches Maven, then the plugins. The second is not.
