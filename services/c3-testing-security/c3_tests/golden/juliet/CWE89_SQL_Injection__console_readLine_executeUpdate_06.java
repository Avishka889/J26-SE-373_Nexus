/* TEMPLATE GENERATED TESTCASE FILE
Filename: CWE89_SQL_Injection__console_readLine_executeUpdate_06.java
*/
package testcases.CWE89_SQL_Injection.s01;

public class CWE89_SQL_Injection__console_readLine_executeUpdate_06 extends AbstractTestCase
{
    public void bad() throws Throwable
    {
        String data = readerBuffered.readLine();
        /* POTENTIAL FLAW: data concatenated into SQL */
        sqlStatement.executeUpdate("insert into users values ('" + data + "')");
    }

    private void goodG2B1() throws Throwable
    {
        /* FIX: hardcoded string */
        String data = "foo";
        sqlStatement.executeUpdate("insert into users values ('" + data + "')");
    }

    private void goodB2G1() throws Throwable
    {
        String data = readerBuffered.readLine();
        /* FIX: prepared statement, and a brace in a string: { */
        String message = "not a block }";
        sqlStatement.prepareStatement("insert into users values (?)").setString(1, data);
    }

    public void good() throws Throwable
    {
        goodG2B1();
        goodB2G1();
    }
}
