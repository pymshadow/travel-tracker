import { useState, useEffect } from 'react'
import axios from 'axios'
import './index.css'

const MONTHS_GR = ['', 'Ιαν.', 'Φεβ.', 'Μαρ.', 'Απρ.', 'Μαΐ.', 'Ιουν.', 'Ιουλ.', 'Αυγ.', 'Σεπ.', 'Οκτ.', 'Νοε.', 'Δεκ.']
const fmtGr = (iso) => {
  const [, m, d] = iso.split('-')
  return `${+d} ${MONTHS_GR[+m]}`
}
const nightsOf = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000)

function App() {
  const [tripsData, setTripsData] = useState([])
  const [costOfLiving, setCostOfLiving] = useState({})
  const [lastUpdate, setLastUpdate] = useState('')

  const loadStaticData = async () => {
    try {
      // Σε περιβάλλον παραγωγής θα διαβάζει τα αρχεία που ανέβηκαν στο public/
      const [tripsRes, snapRes, costRes] = await Promise.all([
        axios.get(import.meta.env.BASE_URL + 'trips.json?v=' + new Date().getTime()),
        axios.get(import.meta.env.BASE_URL + 'snapshot.json?v=' + new Date().getTime()).catch(() => ({ data: {} })),
        axios.get(import.meta.env.BASE_URL + 'cost_of_living.json?v=' + new Date().getTime()).catch(() => ({ data: {} }))
      ])
      setCostOfLiving(costRes.data || {})
      
      const trips = tripsRes.data.trips || []
      const snapshot = snapRes.data || {}
      
      const combined = trips.map(t => ({
        trip: t,
        data: snapshot[t.id] || {}
      }))
      
      setTripsData(combined)
      
      // Υπολογισμός ημερομηνίας (όποτε χτίστηκε ή φόρτωσε)
      setLastUpdate(new Date().toLocaleDateString('el-GR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }))
    } catch (err) {
      console.error("Δεν βρέθηκαν τα δεδομένα. Αν τρέχεις τοπικά, βεβαιώσου ότι τα αρχεία υπάρχουν στο public folder.", err)
    }
  }

  useEffect(() => {
    loadStaticData()
  }, [])

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-6xl mx-auto">
        <header className="mb-12 text-center">
          <h1 className="text-4xl md:text-5xl font-extrabold mb-4 text-gradient tracking-tight">✈️ Travel Price Tracker</h1>
          <p className="text-slate-400 font-medium flex justify-center items-center gap-4 mb-6">
            Τελευταία Ενημέρωση Συστήματος: {lastUpdate}
          </p>
          <div className="inline-block bg-slate-800/80 border border-slate-700/50 rounded-2xl p-4 md:px-8 text-sm md:text-base text-slate-300">
            <span className="font-bold text-blue-400 mb-2 block uppercase tracking-wider text-xs">Αυτόματος Έλεγχος Ημερομηνιών:</span>
            Το σύστημα σκανάρει καθημερινά όλους τους συνδυασμούς για:<br/>
            <span className="text-white font-medium">
              {[...new Map(
                tripsData.flatMap(({ trip }) => trip.date_pairs || [])
                  .map(p => [p.depart + p.return, p])
              ).values()]
                .map(p => `${fmtGr(p.depart)} - ${fmtGr(p.return)} (${nightsOf(p.depart, p.return)} βράδια)`)
                .join(' • ') || '—'}
            </span><br/>
            και εμφανίζει παρακάτω <strong className="text-emerald-400">μόνο την πιο φθηνή επιλογή</strong> για κάθε προορισμό!
          </div>
        </header>

        <div className="space-y-10">
          {tripsData.map(({ trip, data }) => {
            const adults = trip.adults || 1
            const flightMin = data?.flight_min
            const bookingMin = data?.booking_min
            const cityCode = data?.to || trip.to
            const cost = costOfLiving[cityCode]
            const nights = (data?.depart_str && data?.return_str) ? nightsOf(data.depart_str, data.return_str) : 0
            // Κανόνες ωρών πτήσεων: χαλαρώνουν στα ταξίδια 6+ νυχτών
            const outLimit = nights >= 6 ? '17:00' : '13:00'
            const retLimit = nights >= 6 ? '08:00' : '16:30'
            
            return (
              <section key={trip.id} className="glass-card rounded-3xl p-6 md:p-10 overflow-hidden relative hover:border-slate-600/50 transition-colors">
                <div className="absolute -top-6 -right-6 p-4 opacity-5 text-9xl pointer-events-none">🏢</div>
                <div className="flex justify-between items-start mb-3">
                  <h2 className="text-3xl md:text-4xl font-extrabold text-white">{data?.name || trip.name || trip.id}</h2>
                  <div className="text-right mt-2">
                    <div className="bg-slate-800 text-blue-300 px-3 py-1 rounded-full text-xs uppercase tracking-widest border border-slate-700/50">
                      {data?.depart_str ? `${fmtGr(data.depart_str)} – ${fmtGr(data.return_str)} ${data.return_str.split('-')[0]}` : 'N/A'}
                    </div>
                    {nights > 0 && (
                      <div className="text-emerald-400 text-xs font-bold mt-1.5 tracking-wide">🌙 {nights} διανυκτερεύσεις</div>
                    )}
                  </div>
                </div>
                
                <div className="text-slate-400 mb-8 font-medium flex flex-wrap items-center gap-3">
                  <span className="bg-slate-800 text-slate-300 px-3 py-1 rounded-full text-xs uppercase tracking-widest border border-slate-700/50">
                    {trip.from} &rarr; {data?.to || trip.to}
                  </span>
                  <span className="text-slate-500">&bull;</span>
                  <span>{adults} Άτομα</span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mb-8">
                  <div className="bg-slate-800/40 p-5 rounded-2xl border border-slate-700/50 hover:border-slate-600/60 transition-colors shadow-inner">
                    <div className="text-slate-400 text-xs uppercase tracking-wider font-semibold mb-2">Φθηνοτερη Πτηση (Καλοι Κανόνες)</div>
                    <div className="text-4xl font-extrabold text-white">{flightMin ? `${flightMin}€` : '-'}</div>
                    {data?.error && data.error.includes("Πτήσεις") && <div className="text-red-400 text-xs mt-2">{data.error.split("|")[0]}</div>}
                  </div>
                  <div className="bg-slate-800/40 p-5 rounded-2xl border border-slate-700/50 hover:border-slate-600/60 transition-colors shadow-inner">
                    <div className="text-slate-400 text-xs uppercase tracking-wider font-semibold mb-2">Φθηνοτερη Διαμονη (Με Δωρεάν Ακύρωση)</div>
                    <div className="text-4xl font-extrabold text-white">{bookingMin ? `${bookingMin}€` : '-'}</div>
                    {data?.error && data.error.includes("Booking") && <div className="text-red-400 text-xs mt-2">{data.error.split("|").pop()}</div>}
                  </div>
                  <div className="bg-blue-900/40 p-5 rounded-2xl border border-blue-700/50 hover:border-blue-500/60 transition-colors shadow-inner relative overflow-hidden">
                    <div className="absolute top-0 right-0 p-3 opacity-10 text-5xl">💶</div>
                    <div className="text-blue-300 text-xs uppercase tracking-wider font-semibold mb-2">ΣΥΝΟΛΙΚΟ ΚΟΣΤΟΣ (ΑΠΟ)</div>
                    <div className="text-4xl font-extrabold text-white">
                      {(flightMin && bookingMin) ? `${flightMin + bookingMin}€` : '-'}
                    </div>
                    <div className="text-blue-400/80 text-xs mt-2 font-medium">Για όλα τα άτομα ({adults})</div>
                  </div>
                </div>

                {cost && (
                  <div className="bg-slate-800/60 rounded-2xl p-4 md:p-5 mb-8 border border-slate-700/50 shadow-inner">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xl">💳</span>
                      <h3 className="text-sm uppercase tracking-wider font-bold text-slate-300">Εκτιμώμενο Ημερήσιο Κόστος Ζωής για {adults} Άτομα</h3>
                    </div>
                    <p className="text-xs text-slate-500 mb-3">Φαγητό, μετακινήσεις & δραστηριότητες — <strong>χωρίς τη διαμονή</strong> (υπολογίζεται ξεχωριστά παραπάνω)</p>
                    <div className="flex flex-wrap gap-3 mb-3">
                      <span className="px-3 py-1 bg-green-900/40 text-green-400 rounded-full text-sm font-bold border border-green-800/50">Οικονομικά: {cost.low * adults}€</span>
                      <span className="px-3 py-1 bg-blue-900/40 text-blue-400 rounded-full text-sm font-bold border border-blue-800/50">Κανονικά: {cost.mid * adults}€</span>
                      <span className="px-3 py-1 bg-purple-900/40 text-purple-400 rounded-full text-sm font-bold border border-purple-800/50">Άνετα: {cost.high * adults}€+</span>
                    </div>
                    <p className="text-sm text-slate-400">{cost.desc}</p>
                    {cost.url && (
                      <p className="text-xs text-slate-600 mt-2">
                        Πηγή: <a href={cost.url} target="_blank" rel="noreferrer" className="text-slate-500 hover:text-slate-400 underline">Numbeo</a>
                        {costOfLiving._meta?.updated && <span> · ενημ. {costOfLiving._meta.updated}</span>}
                      </p>
                    )}
                  </div>
                )}

                {data?.flights_out && (
                  <div className="mb-8">
                    <h3 className="text-lg font-bold text-white mb-4">Top Αναχωρήσεις <span className="text-slate-500 text-sm font-normal">(κανόνας: έως {outLimit}{nights >= 6 ? ' — χαλαρωμένο λόγω 6+ νυχτών' : ''})</span></h3>
                    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><tbody className="text-slate-300">
                      {data.flights_out.slice(0,3).map((f, i) => (
                        <tr key={i} className="border-b border-slate-800/50">
                          <td className="py-3 font-bold text-white">{f.price}€</td>
                          <td className="py-3">{f.airlines.join(', ')}</td>
                          <td className="py-3">{f.depart} - {f.arrive}</td>
                          <td className="py-3 text-right"><a href={data.flights_out_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 text-xs">Κράτηση</a></td>
                        </tr>
                      ))}
                    </tbody></table></div>
                  </div>
                )}
                
                {data?.flights_ret && (
                  <div className="mb-8">
                    <h3 className="text-lg font-bold text-white mb-4">Top Επιστροφές <span className="text-slate-500 text-sm font-normal">(κανόνας: από {retLimit}{nights >= 6 ? ' — χαλαρωμένο λόγω 6+ νυχτών' : ''})</span></h3>
                    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><tbody className="text-slate-300">
                      {data.flights_ret.slice(0,3).map((f, i) => (
                        <tr key={i} className="border-b border-slate-800/50">
                          <td className="py-3 font-bold text-white">{f.price}€</td>
                          <td className="py-3">{f.airlines.join(', ')}</td>
                          <td className="py-3">{f.depart} - {f.arrive}</td>
                          <td className="py-3 text-right"><a href={data.flights_ret_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 text-xs">Κράτηση</a></td>
                        </tr>
                      ))}
                    </tbody></table></div>
                  </div>
                )}

                {data?.booking && data.booking.length > 0 && (
                  <div>
                    <h3 className="text-lg font-bold text-white mb-4">Top Διαμονές (Κοντά σε Κέντρο/Μετρό)</h3>
                    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><tbody className="text-slate-300">
                      {data.booking.slice(0,3).map((b, i) => (
                        <tr key={i} className="border-b border-slate-800/50">
                          <td className="py-3 font-bold text-white">{b.total}€</td>
                          <td className="py-3 truncate max-w-[200px]" title={b.name}>{b.name}</td>
                          <td className="py-3 text-amber-400 text-xs">{b.rating}★</td>
                          <td className="py-3 text-right"><a href={b.url} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 text-xs">Κράτηση</a></td>
                        </tr>
                      ))}
                    </tbody></table></div>
                  </div>
                )}
              </section>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default App
