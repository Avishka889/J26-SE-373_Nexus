package testcases.CWE89_SQL_Injection.s01;

public class CWE89_SQL_Injection__console_readLine_executeUpdate_11 extends AbstractTestCase
{
    public void bad() throws Throwable
    {
        if (IO.staticReturnsTrue())
        {
            String data = readerBuffered.readLine();
            sqlStatement.executeUpdate("insert into users values ('" + data + "')");
        }
    }

    private void goodG2B1() throws Throwable
    {
        String data = "foo";
        sqlStatement.executeUpdate("insert into users values ('" + data + "')");
    }
}
