package testcases.CWE470_Unsafe_Reflection;

public class CWE470_Unsafe_Reflection__getCookies_Servlet_81_bad extends CWE470_Unsafe_Reflection__getCookies_Servlet_81_base
{
    public void action(String data) throws Throwable
    {
        /* POTENTIAL FLAW: instantiate the class named in data */
        Class<?> found = Class.forName(data);
        found.newInstance();
    }
}
