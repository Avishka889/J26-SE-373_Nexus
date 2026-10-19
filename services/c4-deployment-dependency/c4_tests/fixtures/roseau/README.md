An excerpt of a real Roseau report: `roseau 0.7.0 --diff --v1
org.apache.dubbo:dubbo:2.7.3 --v2 org.apache.dubbo:dubbo:2.7.21 --report JSON=...`,
run on 2026-09-27. The full report has 1,780 breaking changes; these ten entries are
one of each shape the parser has to read (an inherited member reported against the
subclass, a constructor, a type, a field, a changed return type, a new abstract
method, a nested type) and a duplicate, verbatim.
